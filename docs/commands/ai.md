## Command ai ##

If you have the [`openai`](https://github.com/openai/openai-python) Python
module installed, and the `OPENAI_API_KEY` environment variable set to a valid
OpenAI API key, then the `ai` command can be used to query the GPT-3 large
language model for insights into the current debugging context. The register
state, the stack, and the nearby assembly instructions will be made visible
to the model, along with the nearby source code, if the binary was compiled
with debugging information.

Call it via `ai`, followed by your question.



```
gef➤  ai what was the name of the function most recently called?
 strcmp
gef➤  ai how do you know this?
 The assembly code shows that the function call 0x7ffff7fea240 <strcmp> was made just before the current instruction at 0x7ffff7fce2a7 <check_match+103>.
```
