import json
import unittest
from unittest import mock

import numpy as np
import azure.functions as func

import function_app as fa


class DummyModel:
    def __init__(self, scores):
        self._scores = np.array(scores, dtype=np.float32)

    def predict(self, user_idx, all_item_idx, item_features=None):
        # ignore inputs, return fixed scores aligned with all_item_idx
        return self._scores


class FunctionAppTests(unittest.TestCase):
    def setUp(self):
        # Reset global engine before each test
        fa._ENGINE = None

    def _make_engine(self):
        # Two items: idx 0 -> 10, idx 1 -> 11
        return {
            "model": DummyModel([0.1, 0.9]),
            "item_features": None,
            "user_to_idx": {1: 0},
            "idx_to_item": {0: 10, 1: 11},
            "user_seen": {1: [10]},
            "top_k": 5,
            "trending": [99, 98, 97],
            "all_item_idx": np.array([0, 1], dtype=np.int32),
        }

    def test_recommend_unknown_user_fallback_trending(self):
        engine = self._make_engine()
        recs, strategy = fa._recommend(engine, user_id=999, k=2)
        self.assertEqual(strategy, "trending")
        self.assertEqual(recs, [99, 98])

    def test_recommend_known_user_filters_seen(self):
        engine = self._make_engine()
        recs, strategy = fa._recommend(engine, user_id=1, k=2)
        # Item 10 is seen, should recommend 11 then fallback trending
        self.assertEqual(strategy, "lightfm_online")
        self.assertEqual(recs, [11, 99])

    def test_recommend_endpoint_missing_user_id(self):
        req = func.HttpRequest(method="GET", url="/api/recommend", headers={}, params={}, body=None)
        resp = fa.recommend(req)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Missing query parameter", resp.get_body().decode())

    def test_recommend_endpoint_invalid_user_id(self):
        req = func.HttpRequest(method="GET", url="/api/recommend", headers={}, params={"user_id": "abc"}, body=None)
        resp = fa.recommend(req)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("must be an integer", resp.get_body().decode())

    def test_recommend_endpoint_success(self):
        fa._ENGINE = self._make_engine()
        req = func.HttpRequest(method="GET", url="/api/recommend", headers={}, params={"user_id": "1", "k": "2"}, body=None)
        resp = fa.recommend(req)
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.get_body().decode())
        self.assertEqual(payload["user_id"], 1)
        self.assertEqual(payload["strategy"], "lightfm_online")
        self.assertEqual(len(payload["recommended_articles"]), 2)

    def test_recommend_endpoint_cold_start_loads_engine(self):
        engine = self._make_engine()
        with mock.patch.object(fa, "_load_engine_from_blob", return_value=engine):
            req = func.HttpRequest(method="GET", url="/api/recommend", headers={}, params={"user_id": "1"}, body=None)
            resp = fa.recommend(req)
            self.assertEqual(resp.status_code, 200)
            self.assertIsNotNone(fa._ENGINE)


if __name__ == "__main__":
    unittest.main()
