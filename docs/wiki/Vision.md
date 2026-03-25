# Vision

There is a quiet problem in every team building with LLMs. The prompts that drive the system are treated like configuration. A string here, a template there. Someone tweaks a sentence, deploys it, and hopes the output gets better. Nobody versions them. Nobody measures them. Nobody knows which version ran last Tuesday when that customer filed the bug. And when someone finally writes a better prompt, the old one just disappears.

This project starts with a simple conviction: prompts are code. They deserve the same discipline we give to source code. Version control. Testing. Rollback. Measurement. And when the measurement is clear, why should a human be the one rewriting the prompt? The machine that runs the prompt can learn to improve it.

## shonku: the backbone of packaged agents

Most agent frameworks ask you to build something, then figure out how to share it later. shonku inverts this. You start with `shonku init my-agent`, and what you get is a publishable PyPI package from the first line of code. The agent you build can be installed by anyone, run with their own LLM credentials, and composed with tools they define at runtime.

The contract is clean. An agent declares what it needs (`required_tools`). The caller provides those tools. The agent never touches the database, never stores API keys, never assumes where it runs. It is a pure function of its instructions, its tools, and its LLM.

This matters because the future of AI tooling is not monolithic platforms. It is a network of small, composable, single-purpose agents. shonku is the packaging layer that makes that network possible. You build an agent for code review. Someone else builds one for data cleaning. A third person builds one for customer support triage. All installable via pip. All runnable with any LLM. All composable.

Underneath, [agno](https://agno.com) provides the production-grade runtime. shonku does not compete with agno. It sits on top and adds opinions about how agents should be defined, packaged, and distributed.

## autoresearcher-shonku: the backbone of self-improving agents

The autoresearch pattern, borrowed from [Karpathy's work](https://github.com/karpathy/autoresearch), is deceptively simple: try something, measure it, keep what works, discard what doesn't, repeat forever. Applied to neural network training, it produced overnight research sessions that ran a hundred experiments while the researcher slept.

Applied to prompts, it produces something more interesting. The prompt that drives your welcome email is not static. It has a quality score. That score changes over time. An LLM can read the score, read the prompt, read sample interactions, and propose a better version. That version gets shadow-tested at 5% traffic. If the metrics improve, it gets promoted. If they don't, it gets discarded. The loop continues.

But here is the part that keeps me up at night. The meta-prompt that instructs the LLM to improve prompts is itself a prompt. Which means it can be improved by the same loop. If enabled, autoresearcher-shonku will track whether the experiment agent is creating better or worse experiments over time. When the meta-metrics show degradation, the system rewrites its own optimization instructions. The optimizer optimizes itself.

This is not theoretical. The architecture supports it today. A flag in the configuration. A second layer of metrics. The same propose-test-keep-discard loop, applied recursively.

## What comes next

The roadmap, in the order it occupies my thinking:

**Self-improving meta-prompts.** The optimization prompt and the experiment-creation prompt both have measurable outcomes. If the experiments being created are trending worse, the system should rewrite the prompts that create them. This turns autoresearcher from a single optimization loop into a recursive one. The bones are there. The wiring is next.

**Support for more agent runtimes.** shonku wraps agno today. The bridge pattern (a single file that imports the runtime) means adding LangGraph, CrewAI, or raw OpenAI function calling is a matter of writing a new bridge. The agent code never changes. We will support the runtimes people actually use.

**Client SDKs beyond Python.** A TypeScript client for Node.js services. A Go client for infrastructure tools. Generated from the OpenAPI spec so they stay in sync automatically. The resolve endpoint is the hot path and it should be callable from any language.

**Cloud deployment.** A managed version where you do not run PostgreSQL or uvicorn. Push your prompts, configure your experiments, watch the optimization loop run. This is further out, but the architecture is designed for it. The API is stateless. The database is the only state. The agents run ephemerally.

**The autoresearch protocol as a standard.** The propose-test-keep-discard loop is not specific to prompts. It applies to feature flags, model hyperparameters, pricing strategies, email subject lines, UI copy. The protocol is general. The implementation for prompts is the first proof of concept.

This project is small today. Four packages, a hundred and fifty tests, a handful of seed prompts. But the idea underneath is not small. Software that improves itself, measured against outcomes that matter, without a human in the loop. Prompts are just where it starts.
