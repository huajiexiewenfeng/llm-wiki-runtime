from llm_wiki_runtime.policy import (
    assert_read_allowed,
    domain_policy_digest,
    effective_instruction_policy,
    load_domain_policies,
)


def test_readable_by_rejects_hr_by_default():
    policies = {"hr": {"readable_by": []}}
    allowed, reason = assert_read_allowed("learning", "hr", policies)
    assert allowed is False
    assert reason == "domain_not_readable_by_caller"


def test_readable_by_allows_public_domain():
    policies = {"ai-radar": {"readable_by": ["*"]}}
    allowed, reason = assert_read_allowed("learning", "ai-radar", policies)
    assert allowed is True
    assert reason == "ok"


def test_readable_by_allows_first_party_marker():
    policies = {"learning": {"readable_by": ["first_party"]}}
    allowed, reason = assert_read_allowed("hr", "learning", policies, caller_groups=["first_party"])
    assert allowed is True
    assert reason == "ok"


def test_instruction_policy_override_wins():
    policies = {"ai-radar": {"instruction_policy_override": "data_only"}}
    assert effective_instruction_policy("ai-radar", policies, default="trusted_content") == "data_only"


def test_instruction_policy_override_wins_over_caller_default():
    policies = {"ai-radar": {"instruction_policy_override": "data_only"}}
    assert effective_instruction_policy("ai-radar", policies, default="trusted_content") == "data_only"


def test_missing_policy_default_denies_cross_domain_read():
    allowed, reason = assert_read_allowed("learning", "hr", {})
    assert allowed is False
    assert reason == "no_policy_default_deny"


def test_missing_caller_domain_default_denies_target_domain_read():
    policies = {"ai-radar": {"readable_by": ["*"]}}
    allowed, reason = assert_read_allowed(None, "ai-radar", policies)
    assert allowed is False
    assert reason == "no_caller_domain_default_deny"


def test_load_domain_policies_reads_host_file(tmp_path, monkeypatch):
    policy_file = tmp_path / "domain-policies.json"
    policy_file.write_text('{"ai-radar": {"readable_by": ["*"]}}', encoding="utf-8")
    monkeypatch.setenv("LLM_WIKI_DOMAIN_POLICIES", str(policy_file))
    assert load_domain_policies()["ai-radar"]["readable_by"] == ["*"]


def test_domain_policy_digest_is_stable_for_equivalent_mapping_order():
    first = {"hr": {"readable_by": ["learning"], "instruction_policy_override": "data_only"}}
    second = {"hr": {"instruction_policy_override": "data_only", "readable_by": ["learning"]}}

    assert domain_policy_digest(first) == domain_policy_digest(second)
    assert domain_policy_digest(first).startswith("sha256:")
