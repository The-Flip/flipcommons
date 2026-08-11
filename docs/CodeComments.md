# Code Comments

## Explain the why, don't restate the code

Comments should ONLY exist if they explain something the code doesn't. Don't create an alternative source of truth from the code.

## No planning ephemera

**Do NOT reference plan docs**. Neither plans in `/docs/plans/` nor `~/.claude/plans/`. Future readers will not have access to these.

**Do NOT include planning ephemera** — phase/step labels like "PRE3", "REF1", "POST2", "phase", "step N". Those labels will mean nothing to a future reader; they age out the moment the plan is done.

Instead, describe the actual why, rationale, goal or concept.

## No opposition to prior state

By default, don't talk about the prior state of the system, such as "This does NOT do xxx" or "Deliberately NOT derived from xxx". No future reader will know or care about xxx. In rare circumstances prior state IS load-bearing:

- Regression test comments
- DB migrations: these are static, frozen, refer to past state
- It's something a naive reader might legitimately think to change the code back to

## Do not justify over-verbosity with "ratios"

The project is over-documented. Don't defend excessive comments with "it's got the same doc-to-code ratio as the rest of the project". Don't use that as an excuse to avoid the hard work of writing tight just-enough-and-no-more comments.
