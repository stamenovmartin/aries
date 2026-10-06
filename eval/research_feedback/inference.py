"""Explicit study provider; cloud receives only owned synthetic fixtures.

No provider fallback: changing models changes the experimental condition.
"""


def validate_surface(provider, case, controlled_screen):
    if provider != 'local' and case and not controlled_screen:
        raise ValueError('Cloud study requires owned synthetic fixtures; native host observations may contain private data')
    if provider != 'local' and case == 'vf-14':
        raise ValueError('vf-14 also reads live system status; a synthetic auxiliary fixture is required for cloud')


async def generate(db, messages, schema, *, provider, model, timeout):
    if provider == 'local':
        from aries.intelligence import local_structured
        return await local_structured(db, messages, schema,
                                      purpose='research-feedback-loop', max_tokens=700)
    from aries.intelligence.cli import CLIDecisionProvider
    result = await CLIDecisionProvider(provider, model, timeout).generate(messages, schema, 700)
    return result.text, {'provider': result.provider, 'model': result.model,
                         'execution_level': 'cloud', 'fallback': False,
                         'prompt_eval_count': result.input_tokens,
                         'eval_count': result.output_tokens,
                         'usage_details': result.usage_details}
