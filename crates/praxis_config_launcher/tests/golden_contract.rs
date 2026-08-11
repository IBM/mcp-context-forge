use praxis_config_launcher::models::{ContractVector, DirectiveAction};

#[test]
fn python_golden_vector_parses_when_contract_is_v1() {
    // Given
    let raw = include_str!("../../../tests/fixtures/praxis_config/contract-v1.json");

    // When
    let vector: ContractVector = serde_json::from_str(raw).expect("golden vector must parse");

    // Then
    assert_eq!(vector.vector_schema, "praxis-config-contract-vector/v1");
    assert_eq!(vector.input.directive.action, DirectiveAction::Activate);
    assert_eq!(vector.input.snapshot.target_id.as_str(), "target-alpha");
    assert_eq!(
        vector.expected.directive_id.as_str(),
        "fff66e6608eb36b8a231a7e1f22a785de294ae075e44f9dd2d4ec75dacc8ac53"
    );
}

#[test]
fn python_golden_vector_rejects_unknown_fields() {
    // Given
    let raw = include_str!("../../../tests/fixtures/praxis_config/contract-v1.json");
    let mut value: serde_json::Value = serde_json::from_str(raw).expect("fixture JSON");
    value["unexpected"] = serde_json::json!(true);

    // When
    let result = serde_json::from_value::<ContractVector>(value);

    // Then
    assert!(result.is_err());
}
