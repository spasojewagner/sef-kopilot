# UI components

The components in this directory come from [shadcn/ui](https://ui.shadcn.com): style
`new-york` (Radix primitives), base colour `neutral`, from the registry of `shadcn` 4.23.0, the
version pinned in `package.json`. They are part of this code base, to be read, tested and
changed like any other file; nothing updates them behind our backs.

To add one, from `apps/web`, with the configuration in `components.json`:

```bash
pnpm exec shadcn add dialog
```

To compare one with the registry before changing or updating it:

```bash
pnpm exec shadcn add button --diff
```

## License

shadcn/ui is distributed under the MIT License:

```text
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
