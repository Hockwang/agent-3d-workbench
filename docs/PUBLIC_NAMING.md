[简体中文](zh-CN/PUBLIC_NAMING.md)

# Public capability names

Task titles, result cards, model cards, animation menus, and public guides use capability names such as **automatic rigging**, **motion generation**, or **segmentation option A/B**. Research implementation names are not used as default feature labels.

`studio/web/display-label.js` formats legacy task metadata and imported animation labels at display time. Both languages use the same formatter, including saved model labels and newly renamed cards. The agent skill also requests capability-oriented names for new tasks and explanations.

Formatting does not rewrite task IDs, stored evidence, model bytes, skeleton or animation bindings, request parameters, or download filenames. Required dependency license notices are retained. Provider names needed to configure an API connection remain visible.

Regression tests cover both languages, legacy result metadata, model-card titles, unchanged artifact data, and unrelated user labels.
