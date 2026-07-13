---
description: "Review or refine a reusable skill/command. Use when the user provides a draft SKILL.md, command, source notes, or an article and wants actionable improvements to trigger quality, structure, gotchas, progressive disclosure, or maintainability."
---

# Skill Review Rubric

Review a draft skill or command using practical skill-writing heuristics. Do not summarize the source material; turn it into actionable review feedback and targeted rewrites.

## Inputs

Accept pasted content, a file path if repository access is available, or source notes that should become a reusable skill.

If the target is ambiguous, identify the most likely target from context, state the assumption briefly, then continue.

## Review lens

Evaluate the skill in this order:

1. **Trigger and scope**
   - Is it clear when the skill should activate?
   - Does it solve a repeatable problem rather than restating generic advice?
   - Is the scope narrow enough to be useful?

2. **Structure and token economy**
   - Does every section earn its tokens?
   - Is the core file focused?
   - Should heavy examples, references, or scripts move into supporting files?

3. **Operational usefulness**
   - Does the skill tell the model what to do, what to avoid, and what counts as done?
   - Are the instructions specific where correctness matters, and flexible where judgment matters?

4. **Gotchas and failure modes**
   - Does it warn about likely misuse, under-triggering, over-triggering, vague context, or over-constraining the model?
   - Does it prevent the model from producing a summary when the user needs reusable skill design?

5. **Reuse and maintenance**
   - Will it still make sense after the original conversation is forgotten?
   - Can others share, revise, and extend it without needing hidden context?

## Output format

### Verdict
- 1-2 sentences on whether the skill is usable as-is.

### Strong parts
- Short bullets of what already works well.

### Problems to fix
- Prioritized bullets.
- Explain why each issue matters.
- Focus on issues that materially affect trigger quality, usability, or maintenance.

### Redundant parts
- List sections, lines, or ideas that can be removed or merged.
- Explain what to keep instead.

### Suggested rewrite
- Provide improved frontmatter.
- Rewrite only the sections that materially improve the skill.
- Do not replace the entire skill unless the structure itself is the main problem.

### Recommendation
End with one of:
- `Keep as-is`
- `Revise core skill`
- `Split core skill + references`

## Rewrite rules

Preserve the user's intent.
Prefer concise wording.
Do not over-optimize style.
Keep working structure unless it causes under-triggering, over-triggering, confusion, or maintenance cost.

If the content is broad, recommend splitting the core skill from supporting references.
If the content is procedural and repetitive, recommend moving repeatable steps into scripts, templates, or assets.
