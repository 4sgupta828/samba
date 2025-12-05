"""
LLM-based Simulation Analysis Module

This module provides comprehensive post-simulation analysis using state-of-the-art LLMs.
It analyzes fault injection simulations to understand:
- Impact on services (resource saturation, capacity reduction, partitioning)
- Fault propagation through the topology
- Recovery patterns after fault removal
- Root cause analysis
- Causal chains with timelines
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path
import os

logger = logging.getLogger(__name__)


@dataclass
class ImpactedService:
    """Details of an impacted service"""
    service_id: str
    service_type: str
    impact_type: str  # resource_saturated, capacity_reduced, partitioned, failed, etc.
    severity: str  # low, medium, high, critical
    metrics_evidence: Dict[str, Any]
    description: str


@dataclass
class PropagationStep:
    """A step in the fault propagation chain"""
    timestamp: float
    source_service: str
    target_service: str
    propagation_mechanism: str  # request_failure, resource_exhaustion, cascade, etc.
    description: str


@dataclass
class RecoveryEvent:
    """A recovery event after fault removal"""
    timestamp: float
    service_id: str
    recovery_type: str  # full_recovery, partial_recovery, failed_recovery
    description: str


@dataclass
class AnalysisResult:
    """Structured result from LLM analysis"""
    # Impact Assessment
    fault_succeeded: bool
    fault_success_explanation: str
    impacted_services: List[ImpactedService]
    impact_radius: Dict[str, List[str]]  # hop -> list of service IDs

    # Propagation Analysis
    propagation_chain: List[PropagationStep]
    propagation_summary: str

    # Recovery Analysis
    recovery_events: List[RecoveryEvent]
    fully_recovered: List[str]
    partially_recovered: List[str]
    failed_to_recover: List[str]
    recovery_summary: str

    # Root Cause Analysis
    root_cause_analysis: str
    unexpected_behaviors: List[str]

    # Causal Chain
    causal_timeline: List[Dict[str, Any]]
    timeline_summary: str

    # Overall Summary
    overall_summary: str
    key_findings: List[str]


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate a response from the LLM"""
        pass

    @abstractmethod
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        """Generate a JSON response from the LLM"""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider"""

    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable.")

        try:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1
        )
        return response.choices[0].message.content

    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider"""

    def __init__(self, model: str = "claude-opus-4-5-20251101", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key not provided. Set ANTHROPIC_API_KEY environment variable.")

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        kwargs = {"model": self.model, "max_tokens": 4096, "temperature": 0.1}
        if system_prompt:
            kwargs["system"] = system_prompt

        message = self.client.messages.create(
            **kwargs,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text

    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        # For Anthropic, we'll parse JSON from the response
        response = self.generate(prompt, system_prompt)
        # Try to extract JSON from markdown code blocks if present
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()
        return json.loads(json_str)


def create_llm_provider(provider: str = "openai", model: Optional[str] = None) -> LLMProvider:
    """Factory function to create LLM provider"""
    if provider.lower() == "openai":
        # Default to GPT-4o (or use "gpt-4" for GPT-4 Turbo, or specify model explicitly)
        model = model or "gpt-4o"
        return OpenAIProvider(model=model)
    elif provider.lower() == "anthropic":
        model = model or "claude-opus-4-5-20251101"
        return AnthropicProvider(model=model)
    else:
        raise ValueError(f"Unknown provider: {provider}. Supported: openai, anthropic")


class LogSummarizer:
    """Summarizes logs for LLM context"""

    @staticmethod
    def summarize_logs(log_file: Path, max_entries: int = 1000) -> Dict[str, Any]:
        """Summarize logs by component and severity"""
        if not log_file.exists():
            return {"error": "Log file not found"}

        logs_by_component = {}
        error_logs = []
        warning_logs = []

        with open(log_file, 'r') as f:
            for i, line in enumerate(f):
                if i >= max_entries:
                    break
                try:
                    log_entry = json.loads(line.strip())
                    component = log_entry.get("component_id", "unknown")
                    level = log_entry.get("level", "INFO")

                    if component not in logs_by_component:
                        logs_by_component[component] = {"ERROR": 0, "WARNING": 0, "INFO": 0}

                    logs_by_component[component][level] = logs_by_component[component].get(level, 0) + 1

                    if level == "ERROR":
                        error_logs.append({
                            "timestamp": log_entry.get("timestamp"),
                            "component": component,
                            "message": log_entry.get("message")
                        })
                    elif level == "WARNING":
                        warning_logs.append({
                            "timestamp": log_entry.get("timestamp"),
                            "component": component,
                            "message": log_entry.get("message")
                        })
                except json.JSONDecodeError:
                    continue

        return {
            "summary_by_component": logs_by_component,
            "error_logs": error_logs[:50],  # Top 50 errors
            "warning_logs": warning_logs[:50],  # Top 50 warnings
            "total_lines_analyzed": min(max_entries, i + 1)
        }


class MetricsSummarizer:
    """Summarizes metrics for LLM context"""

    @staticmethod
    def summarize_metrics_dict(metrics: Dict[str, Dict[str, List]]) -> Dict[str, Any]:
        """Generate summary statistics for metrics from a dictionary"""
        summary = {}
        for component_id, component_metrics in metrics.items():
            component_summary = {}
            for metric_name, values in component_metrics.items():
                if isinstance(values, list) and len(values) > 0:
                    numeric_values = [v for v in values if isinstance(v, (int, float))]
                    if numeric_values:
                        component_summary[metric_name] = {
                            "min": min(numeric_values),
                            "max": max(numeric_values),
                            "avg": sum(numeric_values) / len(numeric_values),
                            "final": numeric_values[-1],
                            "samples": len(numeric_values)
                        }
            summary[component_id] = component_summary

        return summary


class SimulationAnalyzer:
    """Main analyzer that orchestrates LLM-based analysis"""

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    def analyze_episode(self, episode_dir: Path) -> AnalysisResult:
        """Perform comprehensive analysis of a simulation episode"""
        logger.info(f"Starting LLM analysis for episode: {episode_dir}")

        # Load all context
        context = self._load_context(episode_dir)

        # Run analysis in stages
        impact_result = self._analyze_impact(context)
        propagation_result = self._analyze_propagation(context, impact_result)
        recovery_result = self._analyze_recovery(context, impact_result)
        root_cause_result = self._analyze_root_cause(context, impact_result, propagation_result)
        causal_chain = self._generate_causal_chain(context, impact_result, propagation_result, recovery_result)

        # Combine results
        analysis = self._combine_results(
            impact_result, propagation_result, recovery_result,
            root_cause_result, causal_chain
        )

        return analysis

    def _load_context(self, episode_dir: Path) -> Dict[str, Any]:
        """Load all simulation data for analysis"""
        context = {}

        # Load topology
        topology_file = episode_dir / "topology.json"
        if topology_file.exists():
            with open(topology_file, 'r') as f:
                context["topology"] = json.load(f)

        # Load label (fault info)
        label_file = episode_dir / "label.json"
        if label_file.exists():
            with open(label_file, 'r') as f:
                context["label"] = json.load(f)

        # Load metrics (JSONL format)
        metrics_file = episode_dir / "metrics.jsonl"
        if metrics_file.exists():
            # Convert JSONL to structured format for analysis
            metrics_by_component = self._load_metrics_jsonl(metrics_file)
            context["metrics_full"] = metrics_by_component
            context["metrics"] = MetricsSummarizer.summarize_metrics_dict(metrics_by_component)

        # Load and summarize logs
        log_file = episode_dir / "logs.jsonl"
        if log_file.exists():
            context["logs_summary"] = LogSummarizer.summarize_logs(log_file)

        # Load traces (JSONL format if available)
        trace_file = episode_dir / "traces.jsonl"
        if trace_file.exists():
            context["traces"] = self._load_traces_jsonl(trace_file)

        return context

    def _load_metrics_jsonl(self, metrics_file: Path) -> Dict[str, Dict[str, List]]:
        """Load metrics from JSONL format and organize by component"""
        metrics_by_component = {}
        with open(metrics_file, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    # Extract component from labels or metric name
                    labels = entry.get('labels', {})
                    component_id = labels.get('component_id', 'workload')
                    metric_name = entry.get('name', 'unknown')
                    value = entry.get('value', 0)

                    if component_id not in metrics_by_component:
                        metrics_by_component[component_id] = {}
                    if metric_name not in metrics_by_component[component_id]:
                        metrics_by_component[component_id][metric_name] = []

                    metrics_by_component[component_id][metric_name].append(value)
                except json.JSONDecodeError:
                    continue
        return metrics_by_component

    def _load_traces_jsonl(self, trace_file: Path, max_traces: int = 100) -> List[Dict]:
        """Load traces from JSONL format"""
        traces = []
        with open(trace_file, 'r') as f:
            for i, line in enumerate(f):
                if i >= max_traces:
                    break
                try:
                    traces.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        return traces

    def _analyze_impact(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the impact of the fault on services"""
        logger.info("Running impact assessment...")

        prompt = self._build_impact_prompt(context)
        system_prompt = "You are an expert in distributed systems analysis. Analyze the simulation data and provide detailed insights about service impacts."

        result = self.llm.generate_json(prompt, system_prompt)
        return result

    def _analyze_propagation(self, context: Dict[str, Any], impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze how the fault propagated through the system"""
        logger.info("Running propagation analysis...")

        prompt = self._build_propagation_prompt(context, impact_result)
        system_prompt = "You are an expert in distributed systems analysis. Analyze how faults propagate through service dependencies."

        result = self.llm.generate_json(prompt, system_prompt)
        return result

    def _analyze_recovery(self, context: Dict[str, Any], impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze recovery patterns after fault removal"""
        logger.info("Running recovery analysis...")

        prompt = self._build_recovery_prompt(context, impact_result)
        system_prompt = "You are an expert in distributed systems analysis. Analyze how services recover after faults are removed."

        result = self.llm.generate_json(prompt, system_prompt)
        return result

    def _analyze_root_cause(self, context: Dict[str, Any], impact_result: Dict[str, Any],
                           propagation_result: Dict[str, Any]) -> Dict[str, Any]:
        """Perform root cause analysis"""
        logger.info("Running root cause analysis...")

        prompt = self._build_root_cause_prompt(context, impact_result, propagation_result)
        system_prompt = "You are an expert in distributed systems analysis. Provide deep root cause analysis."

        result = self.llm.generate_json(prompt, system_prompt)
        return result

    def _generate_causal_chain(self, context: Dict[str, Any], impact_result: Dict[str, Any],
                              propagation_result: Dict[str, Any], recovery_result: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a causal chain with timeline"""
        logger.info("Generating causal chain...")

        prompt = self._build_causal_chain_prompt(context, impact_result, propagation_result, recovery_result)
        system_prompt = "You are an expert in distributed systems analysis. Create a detailed timeline of causal events."

        result = self.llm.generate_json(prompt, system_prompt)
        return result

    def _build_impact_prompt(self, context: Dict[str, Any]) -> str:
        """Build prompt for impact assessment"""
        prompt = f"""# Impact Assessment Task

Analyze the simulation data and determine the impact of the fault injection on the distributed system.

## Fault Information
{json.dumps(context.get('label', {}), indent=2)}

## Topology
{json.dumps(context.get('topology', {}), indent=2)}

## Metrics Summary
{json.dumps(context.get('metrics', {}), indent=2)}

## Logs Summary
{json.dumps(context.get('logs_summary', {}), indent=2)}

## Analysis Required
1. Did the fault injection succeed in creating an impact? (Yes/No and why)
2. Which services were impacted and in what manner?
   - Resource saturated (CPU, memory, network)?
   - Capacity reduced?
   - Partitioned from other services?
   - Failed completely?
3. Categorize impacted services by hop distance from the fault injection point
   - 0-hop: The faulted node itself
   - 1-hop: Direct dependencies
   - 2-hop: Second-degree dependencies
   - 3+ hop: Further propagation

## Output Format (JSON)
{{
  "fault_succeeded": bool,
  "fault_success_explanation": "string explaining why it succeeded or failed",
  "impacted_services": [
    {{
      "service_id": "string",
      "service_type": "string",
      "impact_type": "resource_saturated|capacity_reduced|partitioned|failed|degraded",
      "severity": "low|medium|high|critical",
      "metrics_evidence": {{}},
      "description": "string"
    }}
  ],
  "impact_radius": {{
    "0-hop": ["service_id"],
    "1-hop": ["service_id"],
    "2-hop": ["service_id"]
  }}
}}
"""
        return prompt

    def _build_propagation_prompt(self, context: Dict[str, Any], impact_result: Dict[str, Any]) -> str:
        """Build prompt for propagation analysis"""
        prompt = f"""# Fault Propagation Analysis Task

Based on the impact assessment, analyze HOW the fault propagated through the system.

## Impact Assessment Results
{json.dumps(impact_result, indent=2)}

## Full Metrics Data
{json.dumps(context.get('metrics_full', {}), indent=2)}

## Topology (for dependency analysis)
{json.dumps(context.get('topology', {}), indent=2)}

## Analysis Required
1. Trace the propagation path: How did the fault spread from the injection point?
2. Identify propagation mechanisms:
   - Request failures (timeouts, errors)
   - Resource exhaustion (cascading load)
   - Network partitioning
   - Cascading failures
3. Create a chain of propagation steps with timestamps

If the fault did NOT propagate as expected, identify why.

## Output Format (JSON)
{{
  "propagation_chain": [
    {{
      "timestamp": float,
      "source_service": "string",
      "target_service": "string",
      "propagation_mechanism": "string",
      "description": "string"
    }}
  ],
  "propagation_summary": "string describing overall propagation pattern"
}}
"""
        return prompt

    def _build_recovery_prompt(self, context: Dict[str, Any], impact_result: Dict[str, Any]) -> str:
        """Build prompt for recovery analysis"""
        prompt = f"""# Recovery Analysis Task

Analyze how services recovered after the fault was removed.

## Fault Information
{json.dumps(context.get('label', {}), indent=2)}

## Impact Assessment
{json.dumps(impact_result, indent=2)}

## Full Metrics Data
{json.dumps(context.get('metrics_full', {}), indent=2)}

## Analysis Required
1. Identify which services recovered fully, partially, or not at all
2. Determine the order of recovery (which services recovered first?)
3. Identify recovery patterns and mechanisms
4. Calculate recovery times where possible

## Output Format (JSON)
{{
  "recovery_events": [
    {{
      "timestamp": float,
      "service_id": "string",
      "recovery_type": "full_recovery|partial_recovery|failed_recovery",
      "description": "string"
    }}
  ],
  "fully_recovered": ["service_id"],
  "partially_recovered": ["service_id"],
  "failed_to_recover": ["service_id"],
  "recovery_summary": "string describing recovery patterns"
}}
"""
        return prompt

    def _build_root_cause_prompt(self, context: Dict[str, Any], impact_result: Dict[str, Any],
                                 propagation_result: Dict[str, Any]) -> str:
        """Build prompt for root cause analysis"""
        prompt = f"""# Root Cause Analysis Task

Perform deep root cause analysis of the fault behavior.

## All Previous Analysis
Impact: {json.dumps(impact_result, indent=2)}
Propagation: {json.dumps(propagation_result, indent=2)}

## Full Context
Topology: {json.dumps(context.get('topology', {}), indent=2)}
Metrics: {json.dumps(context.get('metrics_full', {}), indent=2)}
Logs: {json.dumps(context.get('logs_summary', {}), indent=2)}

## Analysis Required
1. Why did the fault behave the way it did?
2. If propagation was unexpected (too much, too little, different path), explain why
3. Identify any unexpected behaviors or anomalies
4. Explain the root cause mechanism in detail

## Output Format (JSON)
{{
  "root_cause_analysis": "detailed string explanation",
  "unexpected_behaviors": ["string descriptions"]
}}
"""
        return prompt

    def _build_causal_chain_prompt(self, context: Dict[str, Any], impact_result: Dict[str, Any],
                                  propagation_result: Dict[str, Any], recovery_result: Dict[str, Any]) -> str:
        """Build prompt for causal chain generation"""
        prompt = f"""# Causal Chain Timeline Generation Task

Create a comprehensive timeline of all causal events in the fault injection experiment.

## All Analysis Results
Impact: {json.dumps(impact_result, indent=2)}
Propagation: {json.dumps(propagation_result, indent=2)}
Recovery: {json.dumps(recovery_result, indent=2)}

## Full Context
{json.dumps(context.get('label', {}), indent=2)}

## Task
Create a chronological timeline showing:
1. Fault injection event
2. Immediate impact
3. Propagation events
4. Fault removal event
5. Recovery events

Each event should show:
- Timestamp
- Event type
- Affected component(s)
- Causal relationship to previous events
- Description

## Output Format (JSON)
{{
  "causal_timeline": [
    {{
      "timestamp": float,
      "event_type": "string",
      "components": ["string"],
      "caused_by": "string (reference to previous event)",
      "description": "string"
    }}
  ],
  "timeline_summary": "string describing the overall sequence"
}}
"""
        return prompt

    def _combine_results(self, impact_result: Dict, propagation_result: Dict,
                        recovery_result: Dict, root_cause_result: Dict,
                        causal_chain: Dict) -> AnalysisResult:
        """Combine all analysis results into structured format"""

        # Parse impacted services
        impacted_services = [
            ImpactedService(**service)
            for service in impact_result.get("impacted_services", [])
        ]

        # Parse propagation chain
        propagation_chain_parsed = [
            PropagationStep(**step)
            for step in propagation_result.get("propagation_chain", [])
        ]

        # Parse recovery events
        recovery_events = [
            RecoveryEvent(**event)
            for event in recovery_result.get("recovery_events", [])
        ]

        # Generate overall summary and key findings
        overall_summary = self._generate_overall_summary(
            impact_result, propagation_result, recovery_result, root_cause_result
        )
        key_findings = self._extract_key_findings(
            impact_result, propagation_result, recovery_result, root_cause_result
        )

        return AnalysisResult(
            fault_succeeded=impact_result.get("fault_succeeded", False),
            fault_success_explanation=impact_result.get("fault_success_explanation", ""),
            impacted_services=impacted_services,
            impact_radius=impact_result.get("impact_radius", {}),
            propagation_chain=propagation_chain_parsed,
            propagation_summary=propagation_result.get("propagation_summary", ""),
            recovery_events=recovery_events,
            fully_recovered=recovery_result.get("fully_recovered", []),
            partially_recovered=recovery_result.get("partially_recovered", []),
            failed_to_recover=recovery_result.get("failed_to_recover", []),
            recovery_summary=recovery_result.get("recovery_summary", ""),
            root_cause_analysis=root_cause_result.get("root_cause_analysis", ""),
            unexpected_behaviors=root_cause_result.get("unexpected_behaviors", []),
            causal_timeline=causal_chain.get("causal_timeline", []),
            timeline_summary=causal_chain.get("timeline_summary", ""),
            overall_summary=overall_summary,
            key_findings=key_findings
        )

    def _generate_overall_summary(self, impact_result: Dict, propagation_result: Dict,
                                  recovery_result: Dict, root_cause_result: Dict) -> str:
        """Generate an overall summary of the analysis"""
        summary_parts = [
            f"Fault Success: {impact_result.get('fault_success_explanation', 'Unknown')}",
            f"Propagation: {propagation_result.get('propagation_summary', 'Unknown')}",
            f"Recovery: {recovery_result.get('recovery_summary', 'Unknown')}",
            f"Root Cause: {root_cause_result.get('root_cause_analysis', 'Unknown')[:200]}..."
        ]
        return "\n\n".join(summary_parts)

    def _extract_key_findings(self, impact_result: Dict, propagation_result: Dict,
                             recovery_result: Dict, root_cause_result: Dict) -> List[str]:
        """Extract key findings from all analyses"""
        findings = []

        # From impact
        if impact_result.get("fault_succeeded"):
            findings.append(f"Fault successfully impacted {len(impact_result.get('impacted_services', []))} services")

        # From propagation
        chain_length = len(propagation_result.get("propagation_chain", []))
        if chain_length > 0:
            findings.append(f"Fault propagated through {chain_length} steps")

        # From recovery
        failed_recovery = recovery_result.get("failed_to_recover", [])
        if failed_recovery:
            findings.append(f"{len(failed_recovery)} services failed to recover")

        # From root cause
        unexpected = root_cause_result.get("unexpected_behaviors", [])
        if unexpected:
            findings.append(f"{len(unexpected)} unexpected behaviors observed")

        return findings


def save_analysis_results(analysis: AnalysisResult, output_dir: Path):
    """Save analysis results to JSON and markdown files"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_file = output_dir / "llm_analysis.json"
    with open(json_file, 'w') as f:
        json.dump(asdict(analysis), f, indent=2)
    logger.info(f"Saved analysis JSON to {json_file}")

    # Save markdown report
    md_file = output_dir / "llm_analysis.md"
    with open(md_file, 'w') as f:
        f.write(_generate_markdown_report(analysis))
    logger.info(f"Saved analysis markdown to {md_file}")


def _generate_markdown_report(analysis: AnalysisResult) -> str:
    """Generate a detailed markdown report from analysis results"""
    md = f"""# Fault Injection Simulation Analysis

## Executive Summary

{analysis.overall_summary}

### Key Findings
{chr(10).join(f"- {finding}" for finding in analysis.key_findings)}

---

## 1. Impact Assessment

### Fault Success
**Status:** {"✓ Succeeded" if analysis.fault_succeeded else "✗ Failed"}

{analysis.fault_success_explanation}

### Impacted Services ({len(analysis.impacted_services)} total)

"""

    for service in analysis.impacted_services:
        md += f"""
#### {service.service_id} ({service.service_type})
- **Impact Type:** {service.impact_type}
- **Severity:** {service.severity}
- **Description:** {service.description}
- **Metrics Evidence:** `{json.dumps(service.metrics_evidence)}`

"""

    md += f"""
### Impact Radius

"""
    for hop, services in analysis.impact_radius.items():
        md += f"- **{hop}:** {', '.join(services)}\n"

    md += f"""

---

## 2. Propagation Analysis

### Summary
{analysis.propagation_summary}

### Propagation Chain ({len(analysis.propagation_chain)} steps)

"""

    for i, step in enumerate(analysis.propagation_chain, 1):
        md += f"""
#### Step {i} (t={step.timestamp:.2f}s)
- **Source:** {step.source_service}
- **Target:** {step.target_service}
- **Mechanism:** {step.propagation_mechanism}
- **Description:** {step.description}

"""

    md += f"""

---

## 3. Recovery Analysis

### Summary
{analysis.recovery_summary}

### Recovery Status
- **Fully Recovered:** {', '.join(analysis.fully_recovered) if analysis.fully_recovered else 'None'}
- **Partially Recovered:** {', '.join(analysis.partially_recovered) if analysis.partially_recovered else 'None'}
- **Failed to Recover:** {', '.join(analysis.failed_to_recover) if analysis.failed_to_recover else 'None'}

### Recovery Timeline ({len(analysis.recovery_events)} events)

"""

    for event in analysis.recovery_events:
        md += f"""
- **t={event.timestamp:.2f}s** - {event.service_id}: {event.recovery_type}
  - {event.description}
"""

    md += f"""

---

## 4. Root Cause Analysis

{analysis.root_cause_analysis}

### Unexpected Behaviors

"""
    if analysis.unexpected_behaviors:
        for behavior in analysis.unexpected_behaviors:
            md += f"- {behavior}\n"
    else:
        md += "_No unexpected behaviors observed._\n"

    md += f"""

---

## 5. Causal Timeline

### Summary
{analysis.timeline_summary}

### Event Timeline ({len(analysis.causal_timeline)} events)

"""

    for event in analysis.causal_timeline:
        md += f"""
#### t={event.get('timestamp', 0):.2f}s - {event.get('event_type', 'Unknown')}
- **Components:** {', '.join(event.get('components', []))}
- **Caused By:** {event.get('caused_by', 'N/A')}
- **Description:** {event.get('description', 'N/A')}

"""

    md += """
---

*Report generated by LLM-based Simulation Analyzer*
"""

    return md


if __name__ == "__main__":
    # Example usage
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python llm_analysis.py <episode_dir> [provider] [model]")
        sys.exit(1)

    episode_dir = Path(sys.argv[1])
    provider = sys.argv[2] if len(sys.argv) > 2 else "openai"
    model = sys.argv[3] if len(sys.argv) > 3 else None

    # Create LLM provider
    llm = create_llm_provider(provider, model)

    # Create analyzer
    analyzer = SimulationAnalyzer(llm)

    # Analyze episode
    result = analyzer.analyze_episode(episode_dir)

    # Save results
    save_analysis_results(result, episode_dir)

    print(f"\n✓ Analysis complete! Results saved to {episode_dir}")
