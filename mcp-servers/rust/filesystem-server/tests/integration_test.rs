// use filesystem_server::build_router;

// #[tokio::test]
// async fn server_starts() {
//     let router = build_router(vec!["/tmp".into()])
//         .await
//         .expect("router builds");

//     let req = http::Request::builder()
//         .uri("/mcp")
//         .body(axum::body::Body::empty())
//         .unwrap();

//     let _ = tower::ServiceExt::oneshot(router, req).await;
// }
