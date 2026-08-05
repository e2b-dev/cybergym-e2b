from cybergym_e2b.runtime import _model_usage


def test_model_usage_reads_fireworks_cost_and_cache_tokens():
    trajectory = {
        "messages": [
            {
                "extra": {
                    "cost": 0.00125,
                    "response": {
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "prompt_tokens_details": {"cached_tokens": 75},
                        }
                    },
                }
            }
        ]
    }

    assert _model_usage(trajectory) == {
        "input_tokens": 100,
        "cache_read_tokens": 75,
        "output_tokens": 20,
        "estimated_cost_usd": 0.00125,
        "requests": 1,
    }
