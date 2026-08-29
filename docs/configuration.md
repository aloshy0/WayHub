# Configuration & Customization Guide

This document explains how to customize the Waybar layout, Wofi theme, helper scripts, and icons to fit your desktop setup.

## Font Requirements

Both Waybar and Wofi configurations are set to use **JetBrainsMono Nerd Font** by default:
- Waybar: `font-family: "JetBrainsMono Nerd Font";` in [style.css](file:///home/michael/Projects/waybar/waybar/style.css)
- Wofi: `font-family: "JetBrainsMono Nerd Font";` in [style.css](file:///home/michael/Projects/waybar/wofi/style.css)

If you wish to change the font, make sure to update the font-family declaration in both CSS files. You must also ensure that the chosen font supports the unicode symbols (such as Nerdfont icons like ``, ``, `󰤨`).

---

## Waybar Styling (`~/.config/waybar/`)

### Position & Layout
In [config.jsonc](file:///home/michael/Projects/waybar/waybar/config.jsonc), you can adjust:
* **Position**: Set `"position": "top"` or `"bottom"`, `"left"`, `"right"`.
* **Height**: Adjust `"height": 30` to make the bar thicker or thinner.
* **Margins**: Set top/left/right margins to control gaps around the status bar.

### Sizing and Spacing
In [style.css](file:///home/michael/Projects/waybar/waybar/style.css):
* Modifying the border-radius of `#custom-launcher`, `#network`, `#bluetooth`, etc. allows you to change the roundness of the buttons.
* Modifying `margin` or `padding` inside the `#network`, `#bluetooth`, etc. modules changes their spacing and padding.
* All icons are auto-centered. To change the width/height of status boxes, adjust the `min-width` and `min-height` attributes (default is `38px`).

---

## Wofi Customization (`~/.config/wofi/`)

### Dimensions
In [config](file:///home/michael/Projects/waybar/wofi/config), you can configure default dimensions:
* `width=420`
* `height=450`

*Note: The scripts override these dimensions dynamically for smaller dialog boxes (such as prompt inputs).*

### Colors & Styling
In [style.css](file:///home/michael/Projects/waybar/wofi/style.css):
* To customize the entry select highlight color, update the `#entry:selected` block:
  ```css
  #entry:selected {
      background-color: rgba(37, 167, 255, 0.18); /* Brighter selection box */
      color: #25a7ff;                             /* Selection text color */
  }
  ```
* To change the search input borders on focus, update the `#input:focus` selector.
