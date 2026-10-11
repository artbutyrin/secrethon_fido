import fs from 'fs';

const path =
  'C:/Users/Artem/.cursor/projects/c-Users-Artem-Documents-HAKATON-secrethon-FIdo/agent-tools/10f29d10-43f9-4477-8265-502b92aed551.txt';
const reg = JSON.parse(fs.readFileSync(path, 'utf8'));

for (const f of reg.files) {
  const out = f.path.includes('css')
    ? 'src/components/DitherVeil/DitherVeil.css'
    : 'src/components/DitherVeil/DitherVeil.jsx';
  let content = f.content;
  if (out.endsWith('.jsx') && content.includes('return;\n};')) {
    content = content.replace(
      'return;\n};',
      `return (
    <div
      ref={containerRef}
      className={\`dither-veil\${className ? \` \${className}\` : ''}\`}
      style={style}
    />
  );
};`,
    );
  }
  fs.writeFileSync(out, content);
  console.log('wrote', out, content.length);
}
