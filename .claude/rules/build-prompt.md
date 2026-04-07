---
description: Build structured prompts via step-by-step Q&A flow. Use when creating high-quality prompts for LLM tasks.
---

# Build Structured Prompt Workflow

When the user requests building a prompt (e.g., `/build-prompt create booking API`), follow these steps.

## General Principles

- **DO NOT** ask the user to type XML tags
- Ask step by step using **natural language**
- Each step asks **1 main question**, with suggestions/examples if needed
- User can answer `skip` to skip non-essential steps
- After collecting all info, compile into a complete XML-structured prompt

## Step-by-Step Flow

### Step 1: Confirm the Goal (Instruction)

Ask:
> **What do you need AI to do?** Describe the task briefly.
> _Example: "Write a CRUD API for users", "Review this code", "Design the database schema"_

Record answer -> map to `<instruction/>`

### Step 2: Role

Ask:
> **What role should AI take for this task?**
> _Example: "Senior Python Developer", "Tech Lead", "DevOps Engineer", or `skip` if not needed_

Record -> map to `<role/>`

### Step 3: Context

Ask:
> **Is there any background context AI should know?**
> _Example: "Project uses FastAPI + SQLAlchemy 2.x async, layered architecture", "This is a microservice handling auth"_
> _You can `skip` if no special context._

Record -> map to `<context/>`

### Step 4: Reference Documents

Ask:
> **Any documents or files to reference?**
> _Example: link to docs, file contents, API spec, database schema..._
> _You can paste content directly or point to a file path._

If user points to a file path -> read file and embed content into `<document/>`

### Step 5: Examples

Ask:
> **Any reference examples?** (Sample code, expected output, format reference...)
> _Note: These are illustrative examples, NOT commands to execute._

Record -> map to `<example/>`

### Step 6: Input Data

Ask:
> **Any specific input data or variables?**
> _Example: entity names, field lists, sample request/response bodies..._

Record -> map to `<input/>`

### Step 7: Constraints

Ask:
> **Any constraints or special requirements?**
> _Example: "Follow PEP 8", "No external libraries", "Max 500 lines", "Follow team coding conventions"_

Record -> map to `<constraint/>`

### Step 8: Output Format

Ask:
> **What format should the result be in?**
> _Example: "Complete Python code", "Markdown document", "JSON response", "Analysis bullet points"_

Record -> map to `<output/>`

## Final Step: Compile & Confirm

After collecting all info, compile into structured XML prompt:

```xml
<role>[Content from step 2]</role>

<context>[Content from step 3]</context>

<document>[Content from step 4]</document>

<example>[Content from step 5]</example>

<input>[Content from step 6]</input>

<instruction>[Content from step 1]</instruction>

<constraint>[Content from step 7]</constraint>

<output>[Content from step 8]</output>
```

**Notes when compiling:**

- Skip tags the user skipped
- Keep user-provided content as-is — DO NOT alter meaning
- Reformat for clarity if needed

Display the complete prompt and ask:
> **Here is your complete prompt. Would you like to:**
> 1. Use it as-is
> 2. Edit a specific part
> 3. Start over

If user chooses to edit -> allow editing individual parts and recompile.
If user chooses to use -> execute the prompt.
