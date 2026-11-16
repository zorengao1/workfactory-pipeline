"""Three synthetic text-only cases. This does not execute tool-based stages."""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import http.client
from datetime import datetime, timezone
from pathlib import Path

from contracts import ROOT, STAGES, TOOL_STAGES, output_errors, render


def read_json(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_config(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"").strip("'")
    for key in ["OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY"]:
        if not values.get(key):
            raise ValueError("Missing configuration " + key)
    if not values["OPENAI_BASE_URL"].startswith("https://"):
        raise ValueError("An HTTPS API base URL is required")
    return values


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class IncompleteStreamError(ConnectionError, RuntimeError):
    """A truncated response has no executable tool calls and can be retried."""


def collect_stream(response, log_path=None, secret=''):
    message={'role':'assistant','content':''};calls={};result={'choices':[]};finish=None
    log=Path(log_path).open('w') if log_path else None
    try:
        for raw in response:
            line=raw.decode('utf-8').strip()
            if not line.startswith('data:'):continue
            data=line[5:].strip()
            if data=='[DONE]':break
            chunk=json.loads(data)
            if log:
                safe=json.dumps(chunk,ensure_ascii=False)
                log.write((safe.replace(secret,'[REDACTED]') if secret else safe)+'\n');log.flush()
            if 'error' in chunk:raise RuntimeError('API stream error '+json.dumps(chunk['error']))
            for k in ('id','model','created','usage'):
                if chunk.get(k) is not None:result[k]=chunk[k]
            for choice in chunk.get('choices',[]):
                if choice.get('index',0)!=0:continue
                delta=choice.get('delta',{})
                for key in ('content','reasoning_content','reasoning'):
                    if isinstance(delta.get(key),str):message[key]=message.get(key,'')+delta[key]
                for t in delta.get('tool_calls',[]):
                    call=calls.setdefault(t['index'],{'id':'','type':'function','function':{'name':'','arguments':''}})
                    if t.get('id'):call['id']=t['id']
                    for key in ('name','arguments'):
                        if t.get('function',{}).get(key):call['function'][key]+=t['function'][key]
                if choice.get('finish_reason') is not None:finish=choice['finish_reason']
        if finish is None:raise IncompleteStreamError('API stream ended without finish_reason')
        if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
        result['choices']=[{'index':0,'message':message,'finish_reason':finish}]
        result['stream_reconstructed']=True
        return result
    finally:
        if log:log.close()


def complete_once(config, messages, max_tokens, tool_definitions=None):
    payload = {"model": config["OPENAI_MODEL"], "messages": messages, "max_tokens": max_tokens}
    streaming=config.get('STREAM_RESPONSES')=='1'
    if streaming:payload.update(stream=True,stream_options={'include_usage':True})
    if tool_definitions is not None:
        payload["tools"] = tool_definitions
    request = urllib.request.Request(config["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
        "Authorization": "Bearer " + config["OPENAI_API_KEY"]})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=600) as response:
            result = collect_stream(response,config.get('_STREAM_LOG'),config['OPENAI_API_KEY']) if streaming else json.load(response)
    except urllib.error.HTTPError as exc:
        # Never persist response bodies from auth/transport failures.
        raise RuntimeError("API HTTP " + str(exc.code)) from None
    result = json.loads(json.dumps(result).replace(config["OPENAI_API_KEY"], "[REDACTED]"))
    return result


def complete(config, messages, max_tokens, tool_definitions=None):
    from api_gate import api_slot
    with api_slot(config):
        return _complete_with_retries(config, messages, max_tokens, tool_definitions)


def _complete_with_retries(config, messages, max_tokens, tool_definitions=None):
    attempts=int(config.get('TRANSPORT_ATTEMPTS',1))
    for attempt in range(attempts):
        current=dict(config)
        if attempt and config.get('_STREAM_LOG'):
            p=Path(config['_STREAM_LOG']);current['_STREAM_LOG']=str(p.with_name(p.stem+f'-retry-{attempt:02d}'+p.suffix))
        try:return complete_once(current,messages,max_tokens,tool_definitions)
        except (urllib.error.URLError,http.client.RemoteDisconnected,TimeoutError,ConnectionError) as exc:
            if config.get('_STREAM_LOG'):
                p=Path(config['_STREAM_LOG']).with_suffix('.transport.jsonl')
                with p.open('a') as log:
                    log.write(json.dumps({'attempt':attempt+1,'error_type':type(exc).__name__,'message':str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]')})+'\n')
            if attempt+1==attempts:raise
            time.sleep(min(5*(attempt+1),15))


def run_stage(stage, inputs, destination, config, max_tokens):
    if stage in TOOL_STAGES:
        raise ValueError("Tool execution requires a separate isolated agent harness")
    folder = destination / stage
    folder.mkdir()
    messages = render(stage, inputs)
    save(folder / "request.json", {"model": config["OPENAI_MODEL"], "messages": messages,
         "max_tokens": max_tokens})
    started = time.monotonic()
    try:
        response = complete({**config,'_STREAM_LOG':str(folder/'stream.jsonl')}, messages, max_tokens)
    except Exception as exc:
        save(folder / "transport_error.json", {
            "stage": stage, "model": config["OPENAI_MODEL"],
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "error_type": type(exc).__name__,
            "message": str(exc).replace(config["OPENAI_API_KEY"], "[REDACTED]"),
            "accepted_for_pipeline": False})
        raise
    save(folder / "response.json", response)
    content = response["choices"][0]["message"].get("content")
    errors = []
    parsed = None
    try:
        if not isinstance(content, str):
            raise ValueError("missing text output")
        # Do not strip fences or repair JSON silently.
        parsed = json.loads(content)
        errors = output_errors(stage, parsed, inputs)
    except (ValueError, KeyError, TypeError) as exc:
        errors = [type(exc).__name__ + " " + str(exc)]
    result = {"stage": stage, "elapsed_seconds": round(time.monotonic() - started, 2),
              "format_and_contract_pass": not errors, "errors": errors,
              "finish_reason": response["choices"][0].get("finish_reason"),
              "usage": response.get("usage", {}), "returned_model": response.get("model"),
              "status": parsed.get("status") if isinstance(parsed, dict) else None}
    if result["finish_reason"] == "length":
        result["errors"].append("output truncated")
        result["format_and_contract_pass"] = False
    save(folder / "validation.json", result)
    if parsed is not None:
        save(folder / "parsed.json", parsed)
    print(json.dumps({"task_id": inputs["task_id"], **result}, ensure_ascii=False), flush=True)
    if not result["format_and_contract_pass"] or parsed["status"] != "ok":
        return result, None
    return result, parsed["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--cases", default=str(ROOT / "fixtures" / "pilot_cases.json"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-tokens", type=int, default=12000)
    args = parser.parse_args()
    config = load_config(args.config)
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=False)
    cases = read_json(args.cases)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [ROOT / "contracts.py", ROOT / "pilot.py", *sorted((ROOT / "prompts").glob("*.txt"))]}
    metadata = {"started_at": datetime.now(timezone.utc).isoformat(), "model": config["OPENAI_MODEL"],
                "scope": "synthetic text-only intent-review-plan pilot; no environment execution",
                "hashes": hashes, "cases_sha256": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest()}
    save(destination / "metadata.json", metadata)
    summary = []
    for case in cases:
        folder = destination / case["task_id"]
        folder.mkdir()
        stage = case["stage"]
        inputs = {key: case[key] for key in ["task_id", "source_materials", "constraints"]}
        outcomes = []
        try:
            result, intent = run_stage(stage, inputs, folder, config, args.max_tokens)
            outcomes.append(result)
            if intent is not None:
                review_input = {**inputs, "intent": intent}
                result, review = run_stage("02_intent_review", review_input, folder, config, args.max_tokens)
                outcomes.append(result)
                if review is not None and review["verdict"] == "pass":
                    result, plan = run_stage("03_plan", {"task_id": case["task_id"], "intent": intent,
                              "constraints": case["constraints"]}, folder, config, args.max_tokens)
                    outcomes.append(result)
        except Exception as exc:
            message = str(exc).replace(config["OPENAI_API_KEY"], "[REDACTED]")
            outcomes.append({"transport_or_runtime_error": type(exc).__name__, "message": message})
            # Authentication/network/configuration errors require user input, no substitute model.
            summary.append({"task_id": case["task_id"], "outcomes": outcomes})
            save(destination / "summary.json", summary)
            raise
        summary.append({"task_id": case["task_id"], "outcomes": outcomes})
        save(destination / "summary.json", summary)


if __name__ == "__main__":
    main()
