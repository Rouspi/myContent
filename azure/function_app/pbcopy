import azure.functions as func
import datetime
import json
import logging

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="recommend", methods=["GET"])
def recommend(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("recommend called")

    user_id_str = req.params.get("user_id")
    if not user_id_str:
        return func.HttpResponse("Missing query parameter 'user_id'", status_code=400)

    try:
        user_id = int(user_id_str)
    except ValueError:
        return func.HttpResponse("'user_id' must be an integer", status_code=400)

    k = int(req.params.get("k", "5"))

    payload = {
        "user_id": user_id,
        "recommended_articles": [1, 2, 3, 4, 5][:k],
        "strategy": "debug_stub"
    }

    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=200
    )

