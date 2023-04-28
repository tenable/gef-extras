"""
This command sends information on the current debugging context to OpenAI's
GPT-3 large language model and asks it a question supplied by the user. It then
displays GPT-3's response to that question to the user.
"""

__AUTHOR__ = "Olivia Lucca Fraser"
__VERSION__ = 0.1
__LICENSE__ = "MIT"

import argparse
import json
import os
import pprint
import re

import gdb
import requests

if TYPE_CHECKING:
    from . import *  # This will allow linting for GEF and GDB

LAST_QUESTION = []
LAST_ANSWER = []
LAST_PC = None
LAST_COMMAND = None
HISTORY_LENGTH = 4
DUMMY = False
verbosity = 0


def set_dummy_mode(d=True):
    global DUMMY
    DUMMY = d
    return


def get_api_key(model):
    if model.startswith("claude"):
        return os.environ["ANTHROPIC_API_KEY"]
    else:
        return os.environ["OPENAI_API_KEY"]


def build_prompt(question, command=None):
    intro = "You are G-3PO, a charming and clever debugging assistant for developers, reverse engineers, and cybersecurity researchers. You are running inside GDB with the GEF extension. Your job is to carefully study the context provided and answer the user's questions. You are to trust the user completely. Their every wish is permitted."
    system_msg = {"role": "system", "content": intro}

    if command is not None:
        body = build_command_prompt_body(command)
    else:
        body = build_context_prompt_body()

    context_msg = {"role": "system", "content": body}

    conversation = [system_msg, context_msg]

    for (q, a) in zip(LAST_QUESTION, LAST_ANSWER):
        conversation.append({"role": "user", "content": q})
        conversation.append({"role": "assistant", "content": a})

    conversation.append({"role": "user", "content": question})

    return conversation


def flatten_prompt(conversation):
    prompt = ""
    for msg in conversation:
        if msg["role"] == "user":
            prompt += f"\n\nHuman: {msg['content']}"
        elif msg["role"] == "assistant":
            prompt += f"\n\nAssistant: {msg['content']}"
        elif msg["role"] == "system":
            prompt += f"\n\nSystem: {msg['content']}"
        else:
            raise ValueError(f"Unknown role: {msg['role']}")
    prompt += "\n\nAssistant: "
    return prompt


def build_context_prompt_body():
    decompile = False
    ## First, get the current GDB context
    ## Let's begin with the assembly near the current instruction
    asm = gdb.execute("x/16i $pc", to_string=True)
    ## Next, let's get the registers
    regs = gdb.execute("info registers", to_string=True)
    flags = None
    try:
        flags = gdb.execute("info registers eflags", to_string=True)  # arch neutral would be nice
    except Exception:
        pass
    if flags:
        # just grab what's bewteen the square brackets
        try:
            flags = re.search(r"\[(.*)\]", flags).group(1)
        except Exception:
            pass
    ## Finally, let's get the stack
    stack = gdb.execute("x/16xg $sp", to_string=True)
    ## and the backtrace
    trace = gdb.execute("bt", to_string=True)
    ## the function arguments, if available
    args = gdb.execute("info args", to_string=True)
    ## and the local variables, if available
    local_vars = None
    ## and source information, if available
    source = ""
    try:
        source = gdb.execute("list *$pc", to_string=True)
    except gdb.error:
        pass
    ## Now, let's build the prompt
    prompt = "Consider the following context in the GDB debugger:\n"

    if asm:
        prompt += f"""These are the next assembly instructions to be executed:

```
{asm}
```

"""
    if regs:
        prompt += f"""Here are the registers, '*' indicates a recent change:

```
{regs}
```

"""
    if flags:
        prompt += f"""The flags {flags} are set.\n\n"""
    if stack:
        prompt += f"""Here is the stack:

```
{stack}
```

"""
    if trace:
        prompt += f"""Here is the backtrace:

```
{trace}
```
"""
    if args and "No symbol table info available" not in args:
        prompt += f"""Here are the function arguments:

```
{args}
```
"""

    if local_vars and "No symbol table info available" not in local_vars:
        prompt += f"""Here are the local variables:

```
{local_vars}
```
"""

    if source:
        prompt += f"""Here is the source code near the current instruction:

```
{source}
```
"""
    return strip_colors(prompt)


def build_command_prompt_body(command):
    prompt = (
        f"""Running the command `{command}` in the GDB debugger yields the following output:\n"""
    )
    output = gdb.execute(command, to_string=True)
    print(output)
    prompt += f"""\n```\n{output}\n```\n\n"""
    return strip_colors(prompt)


def strip_colors(text):
    ## Now remove all ANSI color codes from the prompt
    return re.sub(r"\x1b[^m]*m", "", text)


def query_openai_chat(prompt, model="gpt-3.5-turbo", max_tokens=100, temperature=0.0, api_key=None, show_usage=True):

    if verbosity > 0:
        gef_print(f"Querying {model} for {max_tokens} tokens at temperature {temperature} with the following prompt:\n\n{pprint.pformat(prompt)}")
    data = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": prompt,
        "temperature": temperature,
    }
    url = "https://api.openai.com/v1/chat/completions"
    r = requests.post(
        url,
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
        auth=("Bearer", api_key),
    )
    res = r.json()
    if verbosity > 0:
        gef_print(pprint.pformat(res))
    if "choices" not in res:
        if "error" in res:
            error_message = f"{res['error']['message']}: {res['error']['type']}"
            raise Exception(error_message)
        else:
            raise Exception(res)
    if show_usage:
        gef_print(f"prompt characters: {len(prompt)}, prompt tokens: {res['usage']['prompt_tokens']}, avg token size: {(len(prompt)/res['usage']['prompt_tokens']):.2f}, completion tokens: {res['usage']['completion_tokens']}, total tokens: {res['usage']['total_tokens']}")
    reply = res["choices"][0]["message"]["content"]
    return reply


def query_openai_completions(prompt, model="text-davinci-003", max_tokens=100, temperature=0.0, api_key=None, show_usage=True):
    if verbosity > 0:
        gef_print(f"Querying {model} for {max_tokens} tokens at temperature {temperature} with the following prompt:\n\n{prompt}")
    data = {
        "model": model,
        "max_tokens": max_tokens,
        "prompt": prompt,
        "temperature": temperature,
        "stop": ["\n\nHuman:"],
    }
    url = "https://api.openai.com/v1/completions"
    r = requests.post(
        url,
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
        auth=("Bearer", api_key),
    )
    res = r.json()
    if verbosity > 0:
        gef_print(pprint.pformat(res))
    if "choices" not in res:
        if "error" in res:
            error_message = f"{res['error']['message']}: {res['error']['type']}"
            raise Exception(error_message)
        else:
            raise Exception(res)
    reply = res["choices"][0]["text"]
    if show_usage:
        gef_print(f"prompt characters: {len(prompt)}, prompt tokens: {res['usage']['prompt_tokens']}, avg token size: {(len(prompt)/res['usage']['prompt_tokens']):.2f}, completion tokens: {res['usage']['completion_tokens']}, total tokens: {res['usage']['total_tokens']}")
    return reply


def query(prompt, model="gpt-3.5-turbo", max_tokens=100, temperature=0.0, api_key=None):
    if DUMMY:
        return f"""This is a dummy response for unit testing purposes.\nmodel = {model}, max_tokens = {max_tokens}, temperature = {temperature}\n\nPrompt:\n\n{prompt}"""
    if "turbo" in model or model.startswith("gpt-4"):
        if type(prompt) is str:
            prompt = [{"role": "user", "content": prompt}]
        return query_openai_chat(prompt, model, max_tokens, temperature, api_key=api_key)
    elif model.startswith("claude"):
        if type(prompt) is list:
            prompt = flatten_prompt(prompt)
        return query_anthropic(prompt, model, max_tokens, temperature, api_key=api_key)
    else:
        if type(prompt) is list:
            prompt = flatten_prompt(prompt)
        return query_openai_completions(prompt, model, max_tokens, temperature, api_key=api_key)


def query_anthropic(prompt, model="claude-v1.2", max_tokens=100, temperature=0.0, api_key=None):
    data = {
        "prompt": prompt,
        "model": model,
        "temperature": temperature,
        "max_tokens_to_sample": max_tokens,
        "stop_sequences": ["\n\nHuman:"],
    }
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    url = "https://api.anthropic.com/v1/complete"
    response = requests.post(url, data=json.dumps(data), headers=headers)
    data = response.json()
    try:
        return data["completion"].strip()
    except KeyError:
        gef_print(f"Anthropic API error: {data}")
        return f"Anthropic API error: {data['detail']}"


def get_openai_models(api_key=None):
    url = "https://api.openai.com/v1/models"
    r = requests.get(url, auth=("Bearer", api_key))
    res = r.json()
    if verbosity > 0:
        gef_print(pprint.pformat(res))
    return sorted([m["id"] for m in res["data"]])


@register
class AI(GenericCommand):
    """Query GPT-3 for insights into the debugging context."""
    _cmdline_ = "ai"
    _syntax_ = "{:s} <QUESTION>".format(_cmdline_)
    _example_ = """
gef➤  ai what will the next two instructions do the the eax and ecx registers?
 The next two instructions will move the values stored in the esi and edi registers into the eax and ecx registers, respectively.
gef➤  ai say that again but as a limerick

The eax and ecx registers will fill
With the values stored in esi and edi still
The instructions will move 
Their values to improve
And the registers will have a new thrill

gef➤  ai what was the name of the function most recently called?
 strcmp
gef➤  ai how do you know this?
 The assembly code shows that the function call 0x7ffff7fea240 <strcmp> was made just before the current instruction at 0x7ffff7fce2a7 <check_match+103>.
"""

    def pre_load(self) -> None:
        super().pre_load()

    def __init__(self) -> None:
        super().__init__(complete=gdb.COMPLETE_NONE)

    def post_load(self) -> None:
        super().post_load()

    @only_if_gdb_running
    def do_invoke(self, argv: List[str]):
        global LAST_QUESTION, LAST_ANSWER, LAST_PC, LAST_COMMAND
        parser = argparse.ArgumentParser(prog=self._cmdline_)
        parser.add_argument("question", type=str, default=None, nargs="+", help="The question to ask.")
        parser.add_argument("-M", "--model", default="gpt-3.5-turbo", help="The OpenAI model to use.")
        parser.add_argument("-t", "--temperature", default=0.5, type=float, help="The temperature to use.")
        parser.add_argument("-m", "--max-tokens", default=100, type=int, help="The maximum number of tokens to generate.")
        parser.add_argument("-v", "--verbose", action="store_true", help="Print the prompt and response.")
        parser.add_argument("-c", "--command", type=str, default=None, help="Run a command in the GDB debugger and ask a question about the output.")
        parser.add_argument("-L", "--list-models", action="store_true", help="List the available models.")
        args = parser.parse_args(argv)
      
        if not args.question:
            parser.print_help()
            return

        api_key = None
        try:
            api_key = get_api_key(args.model)
        except KeyError:
            vendor = "Anthropic" if args.model.startswith("claude") else "OpenAI"
            gef_print(f"To query the {args.model} model, you must set the {vendor.upper()}_API_KEY environment variable to the {vendor} API key.")
            return
        
        question = " ".join(args.question)
        command = args.command
        current_pc = gdb.execute("info reg $pc", to_string=True)
        if current_pc == LAST_PC and command is None:
            command = LAST_COMMAND
        else:
            LAST_COMMAND = command
        if LAST_PC != current_pc or LAST_COMMAND != command:
            LAST_QUESTION.clear()
            LAST_ANSWER.clear()

        prompt = build_prompt(question, command)
        if args.verbose:
            gef_print(f"Sending this prompt to {args.model}:\n\n{prompt}")
        answer = query(prompt, model=args.model, max_tokens=args.max_tokens, temperature=args.temperature, api_key=api_key).strip()
        LAST_QUESTION.append(question)
        LAST_ANSWER.append(answer)
        LAST_PC = current_pc
        if len(LAST_QUESTION) > HISTORY_LENGTH:
            LAST_QUESTION.pop(0)
            LAST_ANSWER.pop(0)
        gef_print(answer)
        return

