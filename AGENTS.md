# ANTIGRAVITY 2.0 PROJECT RULES & SYSTEM DIRECTIVES

## 1. THE "LOCK IT" IMMUTABILITY RULE
- Whenever the user marks a file, code snippet, function, or component with "LOCK IT", it is PERMANENTLY READ-ONLY.
- NEVER edit, refactor, clean up, rename, or rewrite any locked component.
- If new features require functionality from a locked component, build an external wrapper or modular adapter around it without touching the source file.

## 2. EXTRACTION & SCRAPING ENGINE INTEGRITY
- The existing Python extraction scripts, selectors, data parsers, and scrapers are CRITICAL BASELINES.
- DO NOT alter, optimize, or modify the Python scraping files or data extraction mechanisms when implementing design, styling, layout, or UI changes.
- Ensure strict decoupling: Frontend/design updates must never depend on modifying the backend scraping logic or its output schema.

## 3. CHANGE MANAGEMENT & SAFETY
- Work atomically: Execute only one requested change at a time.
- Verify that scraping scripts, selectors, and locked modules remain completely untouched before presenting any solution.
- If a requested change poses a risk of modifying or breaking locked logic, STOP immediately and ask for explicit confirmation before proceeding.

## 4. COMMIT & VERIFICATION DISCIPLINE
- After completing and verifying every single change, provide the exact Git commit command/message describing the atomic update (e.g., `git commit -m "feat(ui): update layout without altering scraper"`).
- Always keep the workspace in a functional, clean, rollback-ready state.
