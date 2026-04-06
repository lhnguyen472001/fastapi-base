---
description: Build structured prompts via step-by-step Q&A workflow. Use when creating high-quality prompts for LLMs.
---

# Build Structured Prompt Workflow

When user requests building a prompt (e.g., `/build-prompt create booking API`), follow the steps below.

## General Principles
- **DO NOT** ask user to type XML tags
- Ask each step in **natural language**
- Each step asks **1 main question**, with suggestions/examples if needed
- User can answer `skip` to skip optional steps
- After collecting all information, compile into a complete XML prompt

## Step-by-Step Flow

### Step 1: Confirm the Goal (Instruction)
Ask:
> **What do you need the AI to do?** Briefly describe the task.
> _Examples: "Write a booking API", "Review this code", "Analyze system architecture"_

Record answer → map to `<instruction/>`

### Step 2: Role
Ask:
> **What role should the AI take for this task?**
> _Examples: "Senior Python Developer", "Tech Lead", "QA Engineer", or `skip` if not needed_

Record → map to `<role/>`

### Step 3: Context
Ask:
> **Is there any background context the AI needs to know?**
> _Examples: "Project uses FastAPI + SQLAlchemy 2.x, layered architecture", "This is a microservice for bookings"_
> _You can `skip` if no special context is needed._

Record → map to `<context/>`

### Step 4: Reference Documents
Ask:
> **Are there any documents or files to reference?**
> _Examples: documentation links, file contents, API specs, database schemas..._
> _You can paste content directly or specify file paths._

If user specifies file paths → read the files and embed content into `<document/>`

### Step 5: Examples
Ask:
> **Are there any reference examples?** (Sample code, expected output, reference format...)
> _Note: These are illustrative examples, NOT execution commands._

Record → map to `<example/>`

### Step 6: Input Data
Ask:
> **Is there any specific input data or variables?**
> _Examples: entity names, field lists, sample request/response bodies..._

Record → map to `<input/>`

### Step 7: Constraints
Ask:
> **Are there any special constraints or requirements?**
> _Examples: "Use English only", "No external libraries", "Limit to 500 lines", "Follow team coding conventions"_

Record → map to `<constraint/>`

### Step 8: Output Format
Ask:
> **What format should the result be in?**
> _Examples: "Complete Python code", "Markdown document", "JSON response", "Bullet-point analysis"_

Record → map to `<output/>`

## Final Step: Compile & Confirm

After collecting all information, compile into a structured XML prompt:

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
- Skip tags the user chose to `skip`
- Keep user-provided content as-is — DO NOT alter meaning
- Reformat for clarity if needed

Display the complete prompt and ask:
> **Here is the complete prompt. Would you like to:**
> 1. Use it as-is
> 2. Edit a specific section
> 3. Start over

If user chooses to edit → allow editing individual sections and recompile.
If user chooses to use → execute the prompt.
