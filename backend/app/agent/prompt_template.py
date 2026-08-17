import re


class PromptTemplate:
    @staticmethod
    def render(template: str, variables: dict) -> str:
        def replace_var(match: re.Match) -> str:
            key = match.group(1).strip()
            return str(variables.get(key, match.group(0)))

        result = re.sub(r"{{\s*(\w+)\s*}}", replace_var, template)
        return result
