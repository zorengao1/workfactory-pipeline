"""Explicit user-selected backends. Both use the same audited API transport.

Batch size is a number of tasks; concurrency bounds in-flight HTTP requests.
No model substitution is performed on errors.
"""
from workfactory.clients.pilot import complete


def call_deepseek(config, messages, max_tokens=65536, tools=None):
    return complete({**config,'OPENAI_MODEL':'deepseek-v4.1-flash-1017',
                     'API_LIMIT_SCOPE':'model'},messages,max_tokens,tools)


def call_mimo(config, messages, max_tokens=65536, tools=None):
    return complete({**config,'OPENAI_MODEL':'mimo-v2.6-flash',
                     'API_LIMIT_SCOPE':'model'},messages,max_tokens,tools)
