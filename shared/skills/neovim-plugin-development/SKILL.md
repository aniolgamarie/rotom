---
name: neovim-plugin-development
description: Use when implementing or debugging Lua-based Neovim plugins, including API lifecycle, buffers, windows, autocmds, async callbacks, tests, and startup performance.
---

# Neovim Plugin Development

Check:

- supported Neovim versions;
- buffer and window validity;
- autocmd augroup ownership and cleanup;
- namespace, command, and keymap cleanup;
- async callback lifetime;
- global option side effects;
- synchronous I/O on the startup path;
- reloading and duplicate registration behavior.

Prefer direct execution unless the change is cross-module or architectural.

Verification order:

1. `stylua --check`;
2. `luacheck` when configured;
3. headless Neovim smoke test;
4. plenary or busted tests when present;
5. final diff inspection.

Do not repeat an unchanged headless test after it fails.
