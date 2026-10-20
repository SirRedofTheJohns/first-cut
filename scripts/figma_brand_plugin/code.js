// Creates the sample brand used by First Cut's Figma integration: 4 color styles and
// 2 text styles, each applied to a layer in a "Brand Style Guide" frame. The REST API
// returns a style's values through the layers that use it, so the layers must stay.
// Safe to run twice: existing styles with the same name are updated, not duplicated.

const COLORS = [
  ["Brand/Primary", "#C2410C"],
  ["Brand/Secondary", "#FDE68A"],
  ["Neutral/Text", "#1C1917"],
  ["Neutral/Background", "#FFFBF5"],
];

const TEXTS = [
  ["Heading", { family: "Playfair Display", style: "Bold" }, 40, "Fresh sourdough, Monterrey roots"],
  ["Body", { family: "Inter", style: "Regular" }, 16, "Naturally leavened bread, baked daily in Austin, TX."],
];

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}

function autoLayoutFrame(name, direction, spacing) {
  const frame = figma.createFrame();
  frame.name = name;
  frame.layoutMode = direction;
  frame.itemSpacing = spacing;
  frame.primaryAxisSizingMode = "AUTO";
  frame.counterAxisSizingMode = "AUTO";
  return frame;
}

async function main() {
  const paintStyles = new Map((await figma.getLocalPaintStylesAsync()).map((s) => [s.name, s]));
  const textStyles = new Map((await figma.getLocalTextStylesAsync()).map((s) => [s.name, s]));

  const guide = autoLayoutFrame("Brand Style Guide", "VERTICAL", 32);
  guide.paddingTop = guide.paddingBottom = guide.paddingLeft = guide.paddingRight = 40;
  guide.fills = [{ type: "SOLID", color: { r: 1, g: 1, b: 1 } }];

  const swatches = autoLayoutFrame("Colors", "HORIZONTAL", 16);
  swatches.fills = [];
  for (const [name, hex] of COLORS) {
    const style = paintStyles.get(name) || figma.createPaintStyle();
    style.name = name;
    style.paints = [{ type: "SOLID", color: hexToRgb(hex) }];
    const swatch = figma.createRectangle();
    swatch.name = name;
    swatch.resize(120, 120);
    swatch.cornerRadius = 12;
    await swatch.setFillStyleIdAsync(style.id);
    swatches.appendChild(swatch);
  }
  guide.appendChild(swatches);

  await figma.loadFontAsync({ family: "Inter", style: "Regular" }); // default font of new text
  for (const [name, font, size, sample] of TEXTS) {
    await figma.loadFontAsync(font);
    const style = textStyles.get(name) || figma.createTextStyle();
    style.name = name;
    style.fontName = font;
    style.fontSize = size;
    const text = figma.createText();
    text.name = name;
    text.fontName = font;
    text.characters = sample;
    await text.setTextStyleIdAsync(style.id);
    guide.appendChild(text);
  }

  figma.currentPage.appendChild(guide);
  figma.viewport.scrollAndZoomIntoView([guide]);
  figma.closePlugin("✅ Done: 4 color styles + 2 text styles. Now copy the file link (Share → Copy link).");
}

main().catch((error) => figma.closePlugin(`❌ ${error.message}`));
