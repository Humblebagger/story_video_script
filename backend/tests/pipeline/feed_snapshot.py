"""子计划 5 改动前的快照：回喂模型的文字与报告原文（在未改动的代码上跑出来的，不是手写）。
只放数据与造数据的函数，不导入 pipeline；test_llm_feed_snapshot.py 用旧接口核对，test_verify_msgs.py 复用。"""
import copy


def doc():
    """三句原文、三个镜头的最小分镜：结构不全只触发 SCHEMA-001，其余规则全过。"""
    return {"meta": {"narration": {"mode": "original_text"}},
            "source": {"units": [{"id": "u0001", "text": "他推门。", "para": 1},
                                 {"id": "u0002", "text": "“走吧。”", "para": 1},
                                 {"id": "u0003", "text": "门外下雨。", "para": 2}]},
            "assets": {"characters": [], "locations": [], "props": [], "creatures": []},
            "episodes": [{"id": "E01", "shots": [
                {"id": "E01-SH001", "source": {"unit_refs": ["u0001"], "derivation": "explicit"},
                 "narration": {"text": "他推门。", "unit_refs": ["u0001"]}},
                {"id": "E01-SH002", "source": {"unit_refs": ["u0002"], "derivation": "explicit"},
                 "dialogue": [{"text": "走吧。"}]},
                {"id": "E01-SH003", "source": {"unit_refs": ["u0003"], "derivation": "explicit"},
                 "narration": {"text": "门外下雨。", "unit_refs": ["u0003"]}}]}],
            "coverage": {"unmapped_units": [], "inferred_shot_ratio": 0}}


def shot(d, i):
    return d["episodes"][0]["shots"][i]


FROZEN = [{k: u[k] for k in ("id", "text", "para")} for u in doc()["source"]["units"]]

# (规则, 改坏文档, verify_document 的额外参数)：每条只触发它自己
CASES = [
    ("SOURCE-FROZEN-001", lambda d: d["source"]["units"].pop(), {"frozen_units": FROZEN}),
    ("SOURCE-FROZEN-002", lambda d: d["source"]["units"][0].update(text="他推开门。"), {"frozen_units": FROZEN}),
    ("SOURCE-WAIVER-001", lambda d: d["source"]["units"][2].update(skipped=True), {"frozen_units": FROZEN}),
    ("ID-UNIT-001", lambda d: d["source"]["units"][1].update(id="u0001"), {}),
    ("ID-EPISODE-001", lambda d: d["episodes"].append(copy.deepcopy(d["episodes"][0])), {}),
    ("ID-SHOT-001", lambda d: shot(d, 1).update(id="E01-SH001"), {}),
    ("ID-ASSET-001", lambda d: d["assets"]["characters"].extend([{"id": "C01"}, {"id": "C01"}]), {}),
    ("REF-UNIT-001", lambda d: shot(d, 0)["source"]["unit_refs"].append("u0099"), {}),
    ("EVIDENCE-INFERENCE-001", lambda d: shot(d, 0)["source"].update(derivation="inferred"), {}),
    ("EVIDENCE-SHOT-001", lambda d: shot(d, 0)["source"].update(unit_refs=[]), {}),
    ("EVIDENCE-RANGE-001", lambda d: shot(d, 0)["source"].update(unit_refs=["u0001", "u0003"]), {}),
    ("ORDER-001", lambda d: (shot(d, 0)["source"].update(unit_refs=["u0002"]),
                             shot(d, 1)["source"].update(unit_refs=["u0001"])), {}),
    ("FID-DIALOGUE-001", lambda d: shot(d, 1)["dialogue"][0].update(text="快走。"), {}),
    ("REF-NARRATION-001", lambda d: shot(d, 0)["narration"]["unit_refs"].append("u0099"), {}),
    ("FID-NARRATION-001", lambda d: shot(d, 0)["narration"].update(text="他慢慢推门。"), {}),
    ("COVERAGE-001", lambda d: shot(d, 2).pop("narration"), {}),
    ("COVERAGE-DECLARED-001", lambda d: d["coverage"].update(unmapped_units=["u0002"]), {}),
    ("COVERAGE-DECLARED-002", lambda d: d["coverage"].update(inferred_shot_ratio=0.5), {}),
    ("FID-SOURCE-001", lambda d: None, {"original_text": "完全不同的原文"}),
    ("SCHEMA-001", lambda d: None, {}),
]

RULE_MESSAGES = {
    "SOURCE-FROZEN-001": "model changed the deterministic source-unit count",
    "SOURCE-FROZEN-002": "model changed immutable source evidence",
    "SOURCE-WAIVER-001": "skipped source units require an explicit reviewable reason",
    "ID-UNIT-001": "duplicate unit id u0001",
    "ID-EPISODE-001": "duplicate episode id E01",
    "ID-SHOT-001": "duplicate shot id E01-SH001",
    "ID-ASSET-001": "duplicate asset id C01",
    "REF-UNIT-001": "shot references unknown source unit u0099",
    "EVIDENCE-INFERENCE-001": "inferred shots require a concrete derivation note",
    "EVIDENCE-SHOT-001": "non-transition shots require source evidence",
    "EVIDENCE-RANGE-001": "shot evidence should normally be 1-3 adjacent units",
    "ORDER-001": "镜头回跳到更早的原文（上一处 E01-SH001 引至 u0002）",
    "FID-DIALOGUE-001": "dialogue is not a verbatim excerpt of its cited source units",
    "REF-NARRATION-001": "narration references unknown source unit u0099",
    "FID-NARRATION-001": "narration text is not a direct excerpt of its cited source units",
    "COVERAGE-001": "source units are not carried by narration, dialogue, or visuals",
    "COVERAGE-DECLARED-001": "declared coverage differs from deterministic coverage",
    "COVERAGE-DECLARED-002": "declared inferred ratio differs from deterministic result",
    "FID-SOURCE-001": "source units do not reconstruct the normalized input",
    "SCHEMA-001": "'source_range' is a required property",
}
ENGINE_MESSAGE = "jsonschema is unavailable; structural verification cannot run"


def snapshot_doc():
    """一份同时触发 SCHEMA-001、SOURCE-FROZEN-002、ORDER-001、FID-DIALOGUE-001、COVERAGE-001、
    COVERAGE-DECLARED-001 的文档，返回 (文档, 冻结句单元)。"""
    d = doc()
    frozen = [dict(u) for u in FROZEN]
    frozen[2]["text"] = "门外下着雨。"
    s = d["episodes"][0]["shots"]
    s[0]["source"]["unit_refs"] = ["u0002"]
    s[1]["source"]["unit_refs"] = ["u0001"]
    d["episodes"][0]["shots"] = s[:2]
    return d, frozen


SNAPSHOT_RULES = ["COVERAGE-001", "COVERAGE-DECLARED-001", "FID-DIALOGUE-001", "ORDER-001", "SCHEMA-001",
                  "SOURCE-FROZEN-002"]
RENDER = """HIGH [SCHEMA-001] /episodes/0: 'source_range' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/0: 'duration_sec' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/0: 'shot_size' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/0: 'action' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/1: 'duration_sec' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/1: 'shot_size' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/1: 'action' is a required property
HIGH [SCHEMA-001] /episodes/0/shots/1/dialogue/0: 'type' is a required property
HIGH [SCHEMA-001] /meta: 'schema_version' is a required property
HIGH [SCHEMA-001] /meta: 'title' is a required property
HIGH [SCHEMA-001] /meta: 'style' is a required property
CRITICAL [SOURCE-FROZEN-002] /source/units/2/text: model changed immutable source evidence units=u0003
MEDIUM [ORDER-001] /episodes/0/shots/1/source/unit_refs: 镜头回跳到更早的原文（上一处 E01-SH001 引至 u0002） units=u0001
CRITICAL [FID-DIALOGUE-001] /episodes/0/shots/1/dialogue/0/text: dialogue is not a verbatim excerpt of its cited source units units=u0001
CRITICAL [COVERAGE-001] /coverage/unmapped_units: source units are not carried by narration, dialogue, or visuals units=u0002,u0003
HIGH [COVERAGE-DECLARED-001] /coverage/unmapped_units: declared coverage differs from deterministic coverage
COVERAGE selected=3 covered=1 waived=0 failed=2
FAIL (15 hard finding(s))"""
# json.dumps(validation_list, ensure_ascii=False)、repair_request(r, "x")、render() 的 sha256（UTF-8）
SHA = {"validation_list": "b41d55567ed8a1ef76bf5b9f98a73b78aedb747546f2935019a4b7c583eacd76",
       "repair_request": "f510f4135ef6a0c7213c39ec3a7002d146305574a7b56b885140a5f9c8ae0309",
       "render": "fe2d10dd5fc2450479d1da9be1437f1c160342fc0c96166e156efc8a0df2c8ee"}


def soft_case():
    """软核查两条都触发的 (文档, 长期记忆字段)；长期记忆由调用方组成 NovelContext。"""
    s = {"id": "E01-SH001", "action": "地上一摊血", "characters": [{"ref": "C03", "action": "咳嗽"}],
         "source": {"unit_refs": ["u0001"]}}
    ctx = {"lifecycle": [{"character_id": "C03", "type": "deceased"}], "names": {"C03": "小栓"},
           "constraints": [{"text": "不出现血腥画面", "keywords": ["血", "伤口"]}]}
    return {"episodes": [{"shots": [s]}]}, ctx


SOFT_MESSAGES = {
    "NOVEL-CONSTRAINT-001": "镜头 E01-SH001 的画面描述含限制关键词「血」（限制：不出现血腥画面），请人工确认是否违规",
    "NOVEL-LIFECYCLE-001": "镜头 E01-SH001 里出现了已死亡的角色 C03小栓，画面描述里没有回忆/梦境等标记，请人工确认是不是闪回",
}


def chatty(n=4):
    """selective 模式、旁白念满、每镜 1 秒的分镜：两道质量门都不过。"""
    units = [{"id": f"u{i:04d}", "text": f"第{i}句动作描写。", "kind": "action"} for i in range(1, n + 1)]
    shots = [{"id": f"E01-SH{i:03d}", "duration_sec": 1,
              "source": {"unit_refs": [u["id"]] if i % 2 else []},
              "narration": {"text": u["text"] * 3, "unit_refs": [u["id"]]}} for i, u in enumerate(units, 1)]
    return {"meta": {"narration": {"mode": "selective"}}, "source": {"units": units},
            "episodes": [{"id": "E01", "shots": shots}]}


DENSITY = ("[quality] selective 模式下旁白占比 100%，超过阈值 60%——「能拍出来的不念」未执行（人工基准约 20%–35%）。\n"
           "以下被旁白朗读的句子多为可拍内容，请逐句重新裁决，只保留画面承载不了的信息——"
           "时间跳跃、人名身份交代、因果前史、心理核心语义、点题句。\n"
           "已有镜头画面引用、可直接从 narration.unit_refs 中移除的：\n"
           "  u0001 [action] 第1句动作描写。\n  u0003 [action] 第3句动作描写。\n"
           "只靠旁白承载的（没有任何镜头的 source.unit_refs 引用它们）：若要移除，"
           "须先把它加进呈现该内容的镜头的 source.unit_refs，否则就成了未覆盖：\n"
           "  u0002 [action] 第2句动作描写。\n  u0004 [action] 第4句动作描写。")
SPEECH = ("[quality] 2/2 个镜头（100%）的时长不够念完自己的旁白与台词（按 4.5 字/秒），超过阈值 10%。\n"
          "名义总时长 2s，要让语音都念完实际需要 10.7s。\n"
          "上限 15s 以内的缺口程序会自动拉长 duration_sec；超出上限的镜头必须拆成多个镜头分担旁白，"
          "或把画面承载得了的句子从 narration.unit_refs 移除（不得改动旁白与台词文本、也不得改 source.unit_refs）：\n"
          "  E01-SH001 时长 1s，念完需 5.3s（缺 4.3s）\n  E01-SH002 时长 1s，念完需 5.3s（缺 4.3s）")


class Stub:
    """评审模型替身：invoke 返回脚本（raise_ 非空时抛它），text 原样返回。不联网。"""
    def __init__(self, raw="", raise_=None):
        self.raw, self.raise_ = raw, raise_

    def invoke(self, msgs):
        if self.raise_ is not None:
            raise self.raise_
        return self.raw

    def text(self, m):
        return m


LOW_RAW = ('{"scores":{"narration_selection":2,"shot_language":4,"asset_quality":4,"semantic_fidelity":3},'
           '"overall":3.2,"issues":[{"where":"E01-SH002","problem":"旁白重复画面","fix":"删掉旁白"}]}')
HIGH_RAW = ('{"scores":{"narration_selection":5,"shot_language":5,"asset_quality":5,"semantic_fidelity":5},'
            '"overall":5,"issues":[]}')
BAD_RAW = '{"scores":{"x":5}}'
REV_LOW = ("[review] 评审总分 3.2（阈值 3.5）：narration_selection 2；shot_language 4；asset_quality 4；semantic_fidelity 3\n"
           "  [E01-SH002] 旁白重复画面 → 建议：删掉旁白\n"
           "  未通过独立门槛：总分 3.2 < 3.5；低分维度：narration_selection；semantic_fidelity 3 < 4\n\n"
           "请针对上述 issues 逐条修改后重新输出完整 JSON（只输出一个 JSON 对象）。")
REV_HIGH = ("[review] 评审总分 5.0（阈值 3.5）：narration_selection 5；shot_language 5；"
            "asset_quality 5；semantic_fidelity 5\n  无具体问题")
REV_BAD = ("[review] 评审输出不可验证（scores 必须且只能包含 narration_selection, shot_language, asset_quality, "
           "semantic_fidelity）")
REV_AUTH = "[review] 评审服务不可用：AI 服务鉴权失败，请联系管理员"
REV_CALL_FAILED = "[review] 评审服务不可用：调用出错"
