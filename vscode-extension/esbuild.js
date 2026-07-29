// esbuild 配置：编译 src/extension.ts → dist/extension.js
const esbuild = require('esbuild');

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

/** @type {import('esbuild').BuildOptions} */
const buildOptions = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'dist/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  target: 'ES2022',
  sourcemap: !production,
  minify: production,
  logLevel: 'info',
};

async function build() {
  if (watch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    console.log('esbuild watching...');
  } else {
    await esbuild.build(buildOptions);
    console.log('esbuild build complete');
  }
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});