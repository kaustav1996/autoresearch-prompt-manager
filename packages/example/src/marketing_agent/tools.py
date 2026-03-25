"""Tools that bridge the marketing agent to the prompt-manager client."""

from __future__ import annotations

import json

from prompt_manager.client import PromptManagerClient
from shonku import ToolSpec


def create_prompt_manager_tools(client: PromptManagerClient) -> list[ToolSpec]:
    """Create tools that the marketing agent uses to interact with prompt-manager.

    Parameters
    ----------
    client:
        An initialised ``PromptManagerClient`` pointing at the API.

    Returns
    -------
    A list of ``ToolSpec`` objects ready to be passed to ``agent.run(tools=...)``.
    """

    async def resolve_prompt(slug: str, session_id: str = "") -> str:
        """Resolve a prompt template from the prompt manager.

        Parameters
        ----------
        slug:
            The prompt slug to resolve (e.g. ``welcome-email``).
        session_id:
            Optional session ID for experiment bucketing.

        Returns
        -------
        JSON string with the resolved prompt body, version info, and
        available template variables.
        """
        result = await client.resolve(slug, session_id=session_id or None)
        return json.dumps(
            {
                "body": result.body,
                "version": result.version,
                "version_id": str(result.version_id),
                "template_vars": result.template_vars,
            }
        )

    async def report_metric(
        prompt_slug: str, version_id: str, metric_name: str, value: str
    ) -> str:
        """Report a quality metric for a prompt version.

        Parameters
        ----------
        prompt_slug:
            The slug of the prompt being evaluated.
        version_id:
            UUID of the specific version that produced the content.
        metric_name:
            Name of the metric (e.g. ``quality_score``).
        value:
            Numeric value as a string.

        Returns
        -------
        Confirmation message.
        """
        await client.report_metric(
            slug=prompt_slug,
            version_id=version_id,
            metric_name=metric_name,
            value=float(value),
        )
        return f"Metric {metric_name}={value} reported for {prompt_slug}"

    return [
        ToolSpec(
            name="resolve_prompt",
            description=resolve_prompt.__doc__ or "",
            callable=resolve_prompt,
        ),
        ToolSpec(
            name="report_metric",
            description=report_metric.__doc__ or "",
            callable=report_metric,
        ),
    ]
