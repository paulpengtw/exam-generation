from __future__ import annotations

from pathlib import Path

from server.config import ServerConfig
from server.generate.marshalling import question_to_event as _question_to_event
from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params


class _FakeClient:
    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        return {
            "核心問題": "都市更新如何影響居民生活？",
            "文本": "某市正在推動都市更新，居民對公共設施與租金變化有不同看法。",
            "取材來源": ["測試資料"],
            "subquestions": [
                {
                    "序號": 1,
                    "年級": 8,
                    "科目": ["地理"],
                    "核心素養": ["社-J-A2"],
                    "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
                    "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析社會現象"}],
                    "出題概念": "判讀都市更新示意圖",
                    "題型": "選擇題",
                    "題目內容類型": "含圖片",
                    "image_generation_mode": "html",
                    "題目": "根據圖1，居民最可能關注哪一項變化？",
                    "答案": "A",
                    "答案解析": "圖中標示公共設施增加。",
                    "評分規準": [],
                    "chart_spec": {
                        "render_mode": "html",
                        "title": "都市更新前後比較圖",
                        "description": "左側為更新前街區，右側為更新後公共設施增加的街區。",
                        "data": {"更新前": "老舊住宅", "更新後": "公園與捷運站"},
                    },
                }
            ],
            "題目": ["文本", "根據圖1，居民最可能關注哪一項變化？"],
            "正確解題分析": ["A。圖中標示公共設施增加。"],
        }

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        Path(output_path).write_bytes(b"subquestion-png")
        return str(output_path)


class _RepairTopLevelImageClient:
    def __init__(self) -> None:
        self.generate_json_calls = 0

    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        self.generate_json_calls += 1
        if self.generate_json_calls == 1:
            return {
                "核心問題": "都市更新如何影響居民生活？",
                "文本": "某市正在推動都市更新，居民對公共設施與租金變化有不同看法。",
                "取材來源": ["測試資料"],
                "subquestions": [
                    {
                        "序號": 1,
                        "年級": 8,
                        "科目": ["地理"],
                        "核心素養": ["社-J-A2"],
                        "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
                        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析社會現象"}],
                        "出題概念": "判讀都市更新示意圖",
                        "題型": "選擇題",
                        "題目內容類型": "純文字",
                        "image_generation_mode": "html",
                        "題目": "根據文本，居民最可能關注哪一項變化？",
                        "答案": "A",
                        "答案解析": "文本提到公共設施與租金變化。",
                        "評分規準": [],
                    }
                ],
                "題目": ["文本", "根據文本，居民最可能關注哪一項變化？"],
                "正確解題分析": ["A。文本提到公共設施與租金變化。"],
            }
        return {
            "chart_spec": {
                "render_mode": "html",
                "title": "都市更新公共設施示意圖",
                "description": "呈現更新前後街區、公共設施增加與租金變化資訊。",
                "data": {"更新前": "老舊住宅", "更新後": "公園、捷運站、租金上升"},
            }
        }

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        Path(output_path).write_bytes(b"parent-png")
        return str(output_path)


def test_social_studies_subquestion_chart_spec_renders_png(tmp_path: Path) -> None:
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {
                "content_type": "含圖片",
                "image_generation_mode": "gpt_image",
                "instruction": "請聚焦在都市更新前後比較",
            },
        ],
    )

    question = generate_one(
        config=config,
        client=_FakeClient(),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="html",
    )

    assert not isinstance(question, str)
    assert question.subquestions[0].圖片 == "ss_test_sq1.png"
    assert question.subquestions[0].image_generation_mode == "gpt_image"
    assert question.subquestions[0].出題指示 == "請聚焦在都市更新前後比較"
    assert (tmp_path / "ss_test_sq1.png").read_bytes() == b"subquestion-png"


def test_global_image_content_type_repairs_and_renders_parent_png(tmp_path: Path) -> None:
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(seed=1, content_type="含圖片")
    client = _RepairTopLevelImageClient()

    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="gpt_image",
    )

    assert not isinstance(question, str)
    assert client.generate_json_calls == 2
    assert question.chart_spec is not None
    assert question.圖片 == "ss_test.png"
    assert (tmp_path / "ss_test.png").read_bytes() == b"parent-png"

    payload = _question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )
    assert payload["圖片"] == "ss_test.png"
    assert payload["image_base64"] == "cGFyZW50LXBuZw=="


def test_social_studies_subquestion_inherits_request_image_mode(tmp_path: Path) -> None:
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片"},
        ],
    )

    question = generate_one(
        config=config,
        client=_FakeClient(),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="gpt_image",
    )

    assert not isinstance(question, str)
    assert question.subquestions[0].圖片 == "ss_test_sq1.png"
    assert question.subquestions[0].image_generation_mode == "gpt_image"
    assert (tmp_path / "ss_test_sq1.png").read_bytes() == b"subquestion-png"


def test_question_to_event_embeds_subquestion_png(tmp_path: Path) -> None:
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
        ],
    )
    question = generate_one(
        config=config,
        client=_FakeClient(),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="html",
    )
    assert not isinstance(question, str)

    payload = _question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )

    assert payload["subquestions"][0]["圖片"] == "ss_test_sq1.png"
    assert payload["subquestions"][0]["image_base64"] == "c3VicXVlc3Rpb24tcG5n"
