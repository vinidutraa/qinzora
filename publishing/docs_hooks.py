"""Give the documentation theme native keyboard-accessible header controls."""

import re


def on_post_page(output, page, config):
    def button(match):
        target, icon = match.groups()
        name = "Toggle navigation" if target == "__drawer" else "Toggle search"
        return (
            '<button type="button" class="md-header__button md-icon" '
            f'data-toggle="{target}" aria-label="{name}" aria-expanded="false">'
            f"{icon}</button>"
        )

    return re.sub(
        r'<label class="md-header__button md-icon" for="(__drawer|__search)">(.*?)</label>',
        button,
        output,
        flags=re.DOTALL,
    )
