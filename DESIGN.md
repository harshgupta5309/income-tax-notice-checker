---
name: Litigation OS
colors:
  surface: '#fcf9f3'
  surface-dim: '#dcdad4'
  surface-bright: '#fcf9f3'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3ed'
  surface-container: '#f1eee7'
  surface-container-high: '#ebe8e2'
  surface-container-highest: '#e5e2dc'
  on-surface: '#1c1c18'
  on-surface-variant: '#494740'
  inverse-surface: '#31302d'
  inverse-on-surface: '#f3f0ea'
  outline: '#7a776f'
  outline-variant: '#cbc6bd'
  surface-tint: '#605e5b'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#1c1b19'
  on-primary-container: '#868380'
  inverse-primary: '#cac6c2'
  secondary: '#ab341e'
  on-secondary: '#ffffff'
  secondary-container: '#fd6f53'
  on-secondary-container: '#690c00'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#002116'
  on-tertiary-container: '#00966f'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e6e2de'
  primary-fixed-dim: '#cac6c2'
  on-primary-fixed: '#1c1b19'
  on-primary-fixed-variant: '#484644'
  secondary-fixed: '#ffdad3'
  secondary-fixed-dim: '#ffb4a5'
  on-secondary-fixed: '#3e0400'
  on-secondary-fixed-variant: '#8a1c08'
  tertiary-fixed: '#54fdc4'
  tertiary-fixed-dim: '#27e0a9'
  on-tertiary-fixed: '#002116'
  on-tertiary-fixed-variant: '#00513b'
  background: '#fcf9f3'
  on-background: '#1c1c18'
  surface-variant: '#e5e2dc'
typography:
  display-hero:
    fontFamily: DM Serif Display
    fontSize: 72px
    fontWeight: '400'
    lineHeight: '1.1'
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: DM Serif Display
    fontSize: 48px
    fontWeight: '400'
    lineHeight: '1.2'
  headline-lg-mobile:
    fontFamily: DM Serif Display
    fontSize: 32px
    fontWeight: '400'
    lineHeight: '1.2'
  serif-italic:
    fontFamily: DM Serif Display
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.5'
  sans-bold-caps:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '900'
    lineHeight: '1.2'
    letterSpacing: -0.04em
  body-main:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  ledger-mono:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: '1'
    letterSpacing: -0.02em
  ledger-mono-bold:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '700'
    lineHeight: '1'
spacing:
  margin-edge: 48px
  section-padding: 3rem
  grid-unit: 24px
  gutter: 2rem
  stack-lg: 3rem
---

## Brand & Style
The design system embodies a **Neo-Classical Editorial** aesthetic, positioning itself as a high-performance "Drafting Table" for legal professionals. It rejects the softness of modern SaaS interfaces in favor of the permanence found in architectural blueprints and broadsheet newspapers.

The personality is **authoritative, precise, and avant-garde**. It achieves this by mixing traditional editorial elements—generous whitespace and high-contrast serifs—with brutalist technical markers like monospaced ledgers, vector crosshairs, and hard-edged shadows. The emotional response is one of "Technical Reliability"—a system that feels like a physical dossier transformed into a digital operating system.

## Colors
The palette is rooted in the "Parchment and Ink" metaphor. The primary background simulates high-quality paper, while text and structural borders use a deep, carbon-based ink.

- **Primary (Ink):** Used for all structural lines, primary text, and high-level navigation.
- **Secondary (Rust):** Reserved for critical status, "Beta" notifications, and primary action emphasis.
- **Tertiary (Emerald):** A vibrant mint-green used for active states, positive syncing indicators, and verified registry-level information.
- **Neutral (Parchment):** The foundation of the system. In dark mode, this shifts to **Obsidian**, with ink variables inverting to high-opacity white.

Backgrounds for panels should utilize semi-transparent white (light mode) or deep grays (dark mode) with backdrop blurs to maintain the "layered document" feel.

## Typography
The typographic hierarchy creates a tension between classical beauty and technical utility.

1.  **Editorial Layer:** Use **DM Serif Display** for page titles and section headers. Use the italic variant for secondary descriptions and legal issue numbers to soften the technical grid.
2.  **Interface Layer:** **Inter** handles the core functional UI. Use the Heavy (900) weight in all-caps for card titles and brand elements to create a "Brutalist" impact.
3.  **Data Layer:** **JetBrains Mono** is used for all metadata, timestamps, and "ledger" data. It must be used at small scales (9px-11px) to maintain the aesthetic of a technical instrument.

## Layout & Spacing
The system utilizes a **Fixed Grid** philosophy inspired by architectural drafting sheets. 

- **The Blueprint Grid:** A 24px x 24px radial dot pattern serves as the background rhythm. All elements should snap to this 24px increment.
- **Main Layout:** A 3-column structure defined by `48px 1fr 48px`. The outer 48px columns serve as "Vertical Gutters" for labels and navigation markers.
- **Vertical Labels:** Use `writing-mode: vertical-rl` for navigation items in the side margins, creating an editorial edge.
- **Breakpoints:**
  - **Desktop:** Full 48px margins with the dot grid visible.
  - **Tablet:** Margins reduce to 24px; vertical labels transition to horizontal icons.
  - **Mobile:** Margins reduce to 16px; 1-column stack; dot grid hidden to reduce visual noise.

## Elevation & Depth
Depth is communicated through **physical layering** rather than soft lighting.

- **Hard Shadows:** Avoid blurs. Use 100% opacity "ink" shadows (2px to 6px offsets) to create a "stamped" or "cut-out" effect on cards and tabs.
- **Layered Parchment:** Use `backdrop-filter: blur(12px)` on headers and drawers combined with low-opacity white (approx. 20-30%) to simulate semi-translucent paper layers stacked on top of each other.
- **Vector Borders:** Hierarchy is primarily established via 1px "Ink" borders. Use dashed lines specifically for containers that represent processes (e.g., pipelines or summaries).
- **Drafting Markers:** Use "+" symbols at the corners of main panels (Crosshairs) to reinforce the technical drawing metaphor.

## Shapes
The system is predominantly **Sharp (0px)** to maintain its brutalist, technical character.

- **Panels & Buttons:** Must remain 90-degree sharp. 
- **Exception (Directory Cards):** Large high-level category cards use a **20px (rounded-xl)** radius to provide a distinct visual "entry point" that feels friendlier than the data-heavy interior.
- **Exception (Bubbles):** Contextual tooltips or thought bubbles use a **6px** radius to distinguish them from the rigid structural elements.

## Components
- **Buttons:** Sharp 1px borders, Inter Heavy All-caps text. On hover, apply a `4px 4px 0px` hard shadow.
- **Directory Cards:** The "Brutalist" card. Use a `6px 6px 0px` hard shadow, 20px corner radius, and DM Serif Display for the title.
- **Ledger Tables:** No vertical borders. Use 1px horizontal dividers (`--border-ink`). Headers must be in JetBrains Mono at 10px.
- **Tabs:** Active tabs use a 1px border on three sides and a `2px 2px 0px` hard shadow.
- **Input Fields:** 1px solid ink borders, sharp corners. Use JetBrains Mono for placeholder text to signal "data entry."
- **Status Badges:** Small, sharp rectangles using the accent palette (Rust/Emerald).
- **The "Crawler":** Use animated SVG paths for "Processing" states, following a smooth cubic-bezier motion to contrast with the static, rigid grid.