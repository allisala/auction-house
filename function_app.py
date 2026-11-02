"""Three Azure functions for one auction house."""

import json
import logging
import os

import azure.functions as func
from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient, TextBase64EncodePolicy

import auction

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

CONTAINER = "auction"
LOTS_DEADLINE = os.environ.get("AUCTION_DEADLINE", "2026-11-03 18:00:00")


def connection_string():
    """Return the storage connection string when Azure has given us one."""
    conn = os.environ.get("AzureWebJobsStorage", "")
    if conn.startswith("DefaultEndpointsProtocol"):
        return conn
    return ""


def account_name():
    """Return the storage account name used when there is no connection string."""
    return os.environ.get("AzureWebJobsStorage__accountName", "")


def get_queue(name):
    """Open a queue and create it if this is the first bid."""
    conn = connection_string()
    policy = TextBase64EncodePolicy()
    if conn != "":
        client = QueueClient.from_connection_string(conn, name, message_encode_policy=policy)
    else:
        url = "https://" + account_name() + ".queue.core.windows.net"
        client = QueueClient(url, queue_name=name, credential=DefaultAzureCredential(), message_encode_policy=policy)
    try:
        client.create_queue()
    except Exception:
        pass
    return client


def get_blobs():
    """Open blob storage and create the auction container if it is missing."""
    conn = connection_string()
    if conn != "":
        client = BlobServiceClient.from_connection_string(conn)
    else:
        url = "https://" + account_name() + ".blob.core.windows.net"
        client = BlobServiceClient(url, credential=DefaultAzureCredential())
    try:
        client.create_container(CONTAINER)
    except Exception:
        pass
    return client


def read_queue_json(msg):
    """Read a queue message and return the JSON object inside it."""
    raw = msg.get_body().decode("utf-8")
    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)
    return data


def ensure_lot(blobs, lot_id):
    """Create the lot file once, at the starting price."""
    blob = blobs.get_blob_client(CONTAINER, "lots/" + lot_id + ".json")
    if blob.exists():
        return
    state = auction.fresh_lot(lot_id, LOTS_DEADLINE)
    try:
        blob.upload_blob(json.dumps(state), overwrite=False)
    except ResourceExistsError:
        pass


def load_lot(blobs, lot_id):
    """Read a lot and the etag that guards the next write."""
    blob = blobs.get_blob_client(CONTAINER, "lots/" + lot_id + ".json")
    down = blob.download_blob()
    state = json.loads(down.readall())
    return state, down.properties.etag


def save_lot(blobs, lot_id, state, etag):
    """Write the lot only if the etag is still the one we read."""
    blob = blobs.get_blob_client(CONTAINER, "lots/" + lot_id + ".json")
    blob.upload_blob(
        json.dumps(state),
        overwrite=True,
        etag=etag,
        match_condition=MatchConditions.IfNotModified,
    )


@app.route(route="bids", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def receive_bid(req: func.HttpRequest) -> func.HttpResponse:
    """Check the bid, store it, and queue a pointer for the next function."""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Send a JSON body.", status_code=400)
    try:
        bid = auction.check_bid(body, auction.utc_now())
    except (KeyError, TypeError, ValueError) as error:
        text = str(error)
        if text == "":
            text = "Send lot_id, bidder, and amount."
        return func.HttpResponse(text, status_code=400)

    blobs = get_blobs()
    ensure_lot(blobs, bid["lot_id"])
    path = "requests/" + bid["bid_id"] + ".json"
    blob = blobs.get_blob_client(CONTAINER, path)
    try:
        blob.upload_blob(json.dumps(bid), overwrite=False)
    except ResourceExistsError:
        pass
    get_queue("incoming-bids").send_message(json.dumps({"bid_id": bid["bid_id"], "blob": path}))
    logging.info("Queued bid " + bid["bid_id"])
    return func.HttpResponse("Queued bid " + bid["bid_id"], status_code=200)


@app.queue_trigger(arg_name="msg", queue_name="incoming-bids", connection="AzureWebJobsStorage")
def process_bid(msg: func.QueueMessage) -> None:
    """Judge the bid against the current price and retry when the etag clashes."""
    data = read_queue_json(msg)
    blobs = get_blobs()
    bid_blob = blobs.get_blob_client(CONTAINER, data["blob"])
    bid = json.loads(bid_blob.download_blob().readall())
    outcome = None
    for _ in range(12):
        state, etag = load_lot(blobs, bid["lot_id"])
        if bid["bid_id"] in state["applied"]:
            outcome = state["applied"][bid["bid_id"]]
            break
        outcome = auction.judge(state, bid)
        new_state = auction.apply_decision(state, bid, outcome)
        try:
            save_lot(blobs, bid["lot_id"], new_state, etag)
            break
        except ResourceModifiedError:
            outcome = None
            continue
    if outcome is None:
        logging.error("Gave up on " + bid["bid_id"])
        raise RuntimeError("Could not record bid " + bid["bid_id"])
    path = "decisions/" + bid["bid_id"] + ".json"
    blobs.get_blob_client(CONTAINER, path).upload_blob(json.dumps(outcome), overwrite=True)
    get_queue("bid-results").send_message(json.dumps({"bid_id": bid["bid_id"], "blob": path}))
    logging.info(bid["bid_id"] + " " + outcome["reason"])


@app.queue_trigger(arg_name="msg", queue_name="bid-results", connection="AzureWebJobsStorage")
def record_result(msg: func.QueueMessage) -> None:
    """Store one outcome. A second delivery overwrites the same file."""
    data = read_queue_json(msg)
    blobs = get_blobs()
    decision = json.loads(blobs.get_blob_client(CONTAINER, data["blob"]).download_blob().readall())
    path = "results/" + decision["bid_id"] + ".json"
    blobs.get_blob_client(CONTAINER, path).upload_blob(json.dumps(decision), overwrite=True)
    logging.info(decision["bid_id"] + " recorded as " + decision["reason"])
