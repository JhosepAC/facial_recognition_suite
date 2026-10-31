---
name: FaceScan Dark Workspace
description: Restrained native desktop UI for local biometric workflows.
colors:
  accent: "#3ecf8e"
  accent-text: "#65dca5"
  primary-button: "#207f55"
  primary-hover: "#287e58"
  primary-pressed: "#1b6646"
  workspace: "#141414"
  chrome: "#171717"
  panel: "#1c1c1c"
  field: "#212121"
  secondary-button: "#252525"
  border: "#303030"
  field-border: "#404040"
  text: "#ededed"
  muted: "#a3a3a3"
  disabled: "#949494"
  selected: "#20352a"
  selection-border: "#315640"
  focus: "#a1f3c9"
  danger-surface: "#492323"
  danger-text: "#ffb4b4"
  white: "#ffffff"
typography:
  page-heading:
    fontFamily: Segoe UI
    fontSize: 22px
    fontWeight: 700
  section-heading:
    fontFamily: Segoe UI
    fontSize: 16px
    fontWeight: 600
  body:
    fontFamily: Segoe UI
    fontSize: 13px
  supporting:
    fontFamily: Segoe UI
    fontSize: 12px
  statistic:
    fontFamily: Segoe UI
    fontSize: 28px
    fontWeight: 600
rounded:
  control: 6px
  group: 8px
  panel: 12px
spacing:
  compact: 8px
  panel-gap: 12px
  group: 16px
  page: 24px
components:
  button-primary:
    backgroundColor: "{colors.primary-button}"
    textColor: "{colors.white}"
    rounded: "{rounded.control}"
    padding: 8px 14px
  button-secondary:
    backgroundColor: "{colors.secondary-button}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: 8px 14px
  field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: 7px 10px
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
---

# Design System: FaceScan Dark Workspace

## Overview

FaceScan uses a Supabase-inspired dark workspace adapted to native PySide6 controls.
Neutral charcoal surfaces, restrained green selection, and clear control boundaries
support extended webcam recognition and video analysis sessions. The interface is an
operating tool: tasks, evidence, and readable data take priority over decoration.

This document records the dark implementation. `app/gui/theme.py` owns the QSS and
native `QPalette`; the light stylesheet remains a separate legacy theme.

## Colors

The palette is neutral rather than blue-black. Accent green identifies current
navigation, links, progress, and affirmative state. Darker green gives primary
buttons white text without turning every control into a bright accent block.

**The Shared Surface Rule.** Set native palette roles as well as stylesheets.
Scroll viewports and automatically filled containers must inherit the workspace,
base, foreground, and selection colors instead of platform light defaults.

Use muted gray for secondary information, field borders for editable controls,
and the stronger focus tint for keyboard focus. Destructive actions use a dark red
surface with light red text; chart series and recognition warnings retain semantic
colors from their respective components.

## Typography

Segoe UI is the native UI face. Page headings are bold, section headings are
medium or semibold, and supporting labels step down from body text. The dashboard
greeting is a larger heading (24px); statistic values use the dedicated statistic
role. Existing code and measurement readouts may use Consolas, but ordinary
instructions and empty states use the UI face.

Use the bundled Google Material Icons font through `app/gui/icons.py`; icons are
rendered pixmaps or explicit rich-text glyph spans, never the body font.

## Layout

The main window opens at 1360×860 with a minimum of 1040×700 logical pixels.
The sidebar is 232px wide and the top bar is 60px high. Module pages generally
use 24px margins, with tighter spacing inside related control groups.

Each page lives in `WorkspaceArea`, providing scrolling when its minimum content
height exceeds the viewport. Marked splitters stack vertically according to the
available workspace width: webcam below 900px, registration below 1000px, and
video jobs/detail below 1200px. These are content-area thresholds, not overall
window widths. Marked panel splits use a 12px handle and retain native resizing.

## Elevation & Depth

The dark system is flat and uses tonal layering with thin borders. Panels are
slightly lighter than the workspace; controls have distinct field or button
surfaces. There is no shared decorative shadow or glow vocabulary.

## Shapes

Controls use compact rounded corners, groups are slightly softer, and major
panels use the panel radius. Borders are generally one logical pixel. Tabs use
a thin bottom indicator instead of raised tab shapes. Scrollbar handles are
small, rounded, and neutral.

## Components

- **Buttons:** primary actions use dark green; secondary actions use neutral
  surfaces with visible borders. Hover changes the surface or border; focus
  remains visible. Disabled controls use muted text and neutral surfaces.
- **Inputs:** dark field fill, medium neutral border, and green focus border.
  Native palette roles also cover placeholder, selection, and disabled text.
- **Panels:** tonal surfaces with a single border and no decorative elevation.
  Existing modules vary internal padding according to content density.
- **Tables:** neutral headers, row dividers, green-tinted selection, and visible
  focused items. Size or scroll columns deliberately instead of hiding meaning.
- **Navigation:** grouped sidebar entries use a green-tinted selected surface.
  All entry points synchronize the sidebar and workspace title. The `Ctrl+K`
  module palette exposes authorized destinations with filtering and keyboard use.
- **Video and webcam:** preserve the image as the dominant working surface;
  session data, playback controls, jobs, and detections remain separate native
  panels. Compact layouts stack panels and retain scrolling access.

## Do's and Don'ts

- **Do** use the shared stylesheet and native palette for new controls and dialogs.
- **Do** keep keyboard focus, selected state, disabled state, and destructive
  intent visually distinct.
- **Do** check both languages and compact windows with real control text.
- **Don't** introduce blue-black retro chrome, decorative gradients, or neon glows
  into the neutral dark workspace.
- **Don't** replace native resizing, scrolling, or authorization-aware navigation
  with decorative controls that conceal existing functionality.

Authentication uses left-aligned, type-led headings (26px, weight 600), with no decorative header icons. Form actions and existing authentication behavior remain intact.
