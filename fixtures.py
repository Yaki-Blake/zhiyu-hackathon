"""Written for this demo; none of the questions or quotes are from Zhihu."""
EXAMPLE = dict(name="拾句 · 访谈证据摘录", url="/sample", audience="做用户访谈的产品同学和研究者", material="一段脱敏的中文访谈文字稿", task="从访谈稿中找出支持研究结论的原话", output="三句带原文位置的候选引文", limits="只接收文字，不处理录音；引文是否支持结论需要人工核对。")
SOURCES = [
    dict(id="interview", title="整理访谈时，怎样找到能支撑结论的原话？", evidence="我已经有了逐字稿和初步结论，想回到受访者的原话逐句核对，而不是再要一份摘要。", author=None,
         body="小组整理了几次访谈，不同人对同一段话的理解并不一样。我已经有了逐字稿和初步结论，想回到受访者的原话逐句核对，而不是再要一份摘要。有没有办法先缩小查找范围？",
         terms=[["访谈","逐字稿","文字稿"],["结论","原话","引文","证据"]], reason="读者已有文字稿，目标是核对结论与原话；输入和预期产物都吻合。", unknown="摘出的原话是否足以支持结论，仍需读者判断。"),
    dict(id="transcribe", title="只有一段采访录音，怎样先转成文字？", evidence="手里只有录音，没有文字稿。眼下只需要把对话转成文字。", author=None, body="手里只有录音，没有文字稿。眼下只需要把对话转成文字。之后再考虑怎么分析。", terms=[["录音","音频"],["转写","转成文字","转文字"]], reason="读者从录音开始，所需产物是转写文本。", unknown="是否支持实际音频格式还需核实。"),
    dict(id="schedule", title="怎样把多门课的作业截止时间整理成清单？", evidence="每门课的作业说明都分散在不同通知里，我想提取截止时间，按先后排好。", author=None, body="每门课的作业说明都分散在不同通知里，我想提取截止时间，按先后排好。最后要的是一份能逐项核对的任务清单。", terms=[["作业","通知","课程"],["截止","清单","排期"]], reason="读者有课程通知，需要的是提取截止时间后的清单。", unknown="没有明确年份的日期是否能解析，需要另行试用。"),
]
def rank(p):
    inputs=p["material"]; task=p["task"]+" "+p["output"]
    results=[]
    for s in SOURCES:
        hit=[any(w in t for w in group) for group,t in zip(s["terms"],[inputs,task])]
        if all(hit):
            judgment="适配"; reason=s["reason"]
        elif s["id"]=="transcribe" and any(w in p["limits"] for w in ("不处理录音","不支持录音","不支持音频","只接收文字")):
            judgment="排除"; reason="该场景只有录音，而工具声明只处理文字。"
        elif any(hit):
            judgment="待核实"; reason="材料或目标只有一项对应，不能据此判断适用。"
        else: continue
        results.append(dict(id=s["id"],title=s["title"],author=s["author"],url="/source/"+s["id"],sourceType="synthetic",evidence=s["evidence"],judgment=judgment,reason=reason,unknown=s["unknown"]))
    return sorted(results,key=lambda r:["适配","待核实","排除"].index(r["judgment"]))[:3]
