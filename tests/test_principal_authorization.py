import pytest

from llm_wiki_runtime.authorization import AuthorizationError, authorize_query, authorize_write
from llm_wiki_runtime.models import Profile, WriteRule


def principal(*, domain="demo", produced_records=None, supports=None):
    return {
        "domain": domain,
        "produces": [
            {"domain": domain, "record_type": record_type}
            for record_type in (produced_records or [])
        ],
        "supports": list(supports or []),
    }


def mapping(*, owner="demo-harness", domain="demo", record_types=None, source_types=None):
    return {
        "owner_principal_id": owner,
        "domain": domain,
        "produces": [{"record_type": record_type} for record_type in (record_types or [])],
        "source_types": list(source_types or []),
    }


def profile_with_record_types(record_types):
    return Profile(
        id="demo",
        version="v0.1",
        write_rules={
            record_type: WriteRule(record_type, f"domains/demo/{record_type}.md", "create_only")
            for record_type in record_types
        },
    )


def profile_with_demo_record():
    return profile_with_record_types(["demo_record"])


def test_same_domain_query_is_allowed():
    result = authorize_query(
        principal=principal(domain="demo"),
        operation="find_records",
        target_domain="demo",
        domain_policies={},
        caller_groups=[],
    )

    assert result["decision"] == "allowed"
    assert result["domain"] == "demo"


def test_query_rejects_undeclared_supporting_domain():
    with pytest.raises(AuthorizationError) as exc:
        authorize_query(
            principal=principal(domain="demo"),
            operation="load_context",
            target_domain="support",
            domain_policies={"support": {"readable_by": ["demo"]}},
            caller_groups=[],
        )

    assert exc.value.code == "support_not_declared"


def test_query_rejects_host_policy_denial_for_declared_support():
    with pytest.raises(AuthorizationError) as exc:
        authorize_query(
            principal=principal(domain="demo", supports=["support"]),
            operation="resolve",
            target_domain="support",
            domain_policies={"support": {"readable_by": []}},
            caller_groups=[],
        )

    assert exc.value.code == "read_denied"


def test_mapping_owner_mismatch_is_stable_error():
    with pytest.raises(AuthorizationError) as exc:
        authorize_write(
            principal_id="other-harness",
            principal=principal(domain="demo"),
            operation="write_record",
            product={"record_type": "demo_record"},
            mapping=mapping(owner="demo-harness"),
            profile=profile_with_demo_record(),
        )

    assert exc.value.code == "mapping_owner_mismatch"


def test_write_rejects_product_not_declared_by_principal_and_mapping():
    with pytest.raises(AuthorizationError) as exc:
        authorize_write(
            principal_id="demo-harness",
            principal=principal(domain="demo", produced_records=["other_record"]),
            operation="write_record",
            product={"record_type": "demo_record"},
            mapping=mapping(owner="demo-harness", record_types=["other_record"]),
            profile=profile_with_demo_record(),
        )

    assert exc.value.code == "product_not_declared"


def test_manifest_cannot_produce_type_absent_from_profile():
    with pytest.raises(AuthorizationError) as exc:
        authorize_write(
            principal_id="demo-harness",
            principal=principal(domain="demo", produced_records=["demo_record"]),
            operation="write_record",
            product={"record_type": "demo_record"},
            mapping=mapping(owner="demo-harness", record_types=["demo_record"]),
            profile=profile_with_record_types([]),
        )

    assert exc.value.code == "profile_mismatch"


def test_copy_source_is_authorized_by_mapping_source_type():
    result = authorize_write(
        principal_id="demo-harness",
        principal=principal(domain="demo"),
        operation="copy_source",
        product={"source_type": "approved_source"},
        mapping=mapping(owner="demo-harness", source_types=["approved_source"]),
        profile=profile_with_demo_record(),
    )

    assert result == {"operation": "copy_source", "domain": "demo", "decision": "allowed"}


def test_copy_source_rejects_source_type_absent_from_mapping():
    with pytest.raises(AuthorizationError) as exc:
        authorize_write(
            principal_id="demo-harness",
            principal=principal(domain="demo"),
            operation="copy_source",
            product={"source_type": "unapproved_source"},
            mapping=mapping(owner="demo-harness", source_types=["approved_source"]),
            profile=profile_with_demo_record(),
        )

    assert exc.value.code == "product_not_declared"
