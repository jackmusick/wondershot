//! Typed serde models for editor annotation items.
//!
//! These mirror the Python `items.py` `to_dict()`/`from_dict()` JSON contract so
//! the Rust side has a schema-checked view of the opaque
//! `sidecar::SidecarDoc.items` values. Every item carries a `"type"` tag plus
//! shared transform fields (`pos`, `rotation`, `origin`).

use serde::{Deserialize, Serialize};

/// Shared transform fields present on every item.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Transform {
    pub pos: [f64; 2],
    pub rotation: f64,
    pub origin: [f64; 2],
}

/// A single annotation item, internally tagged by `"type"`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Item {
    Arrow {
        p1: [f64; 2],
        p2: [f64; 2],
        color: String,
        width: i64,
        #[serde(flatten)]
        transform: Transform,
    },
    Line {
        p1: [f64; 2],
        p2: [f64; 2],
        color: String,
        width: i64,
        #[serde(flatten)]
        transform: Transform,
    },
    Rect {
        rect: [f64; 4],
        color: String,
        width: i64,
        #[serde(skip_serializing_if = "Option::is_none", default)]
        fill: Option<String>,
        #[serde(flatten)]
        transform: Transform,
    },
    Ellipse {
        rect: [f64; 4],
        color: String,
        width: i64,
        #[serde(flatten)]
        transform: Transform,
    },
    Highlight {
        rect: [f64; 4],
        color: String,
        #[serde(flatten)]
        transform: Transform,
    },
    Freehand {
        points: Vec<[f64; 2]>,
        color: String,
        width: i64,
        #[serde(flatten)]
        transform: Transform,
    },
    Text {
        text: String,
        color: String,
        family: String,
        point_size: i64,
        bold: bool,
        text_width: f64,
        align: String,
        #[serde(flatten)]
        transform: Transform,
    },
    Step {
        number: i64,
        color: String,
        radius: f64,
        #[serde(flatten)]
        transform: Transform,
    },
    Pixelate {
        rect: [f64; 4],
        block: i64,
        #[serde(flatten)]
        transform: Transform,
    },
    Blur {
        rect: [f64; 4],
        radius: i64,
        #[serde(flatten)]
        transform: Transform,
    },
}

/// Image-level effects (rounded corners / fade), matching the Python sidecar.
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct Effects {
    #[serde(default)]
    pub rounded: bool,
    #[serde(default)]
    pub corner_radius: i64,
    #[serde(default)]
    pub fade: bool,
    #[serde(default)]
    pub fade_height: i64,
}

/// Convert typed items to opaque JSON values for `sidecar::SidecarDoc.items`.
pub fn items_to_values(items: &[Item]) -> Vec<serde_json::Value> {
    items.iter().map(|i| serde_json::to_value(i).unwrap()).collect()
}

/// Parse opaque JSON values back into typed items, skipping any that don't match.
pub fn items_from_values(values: &[serde_json::Value]) -> Vec<Item> {
    values
        .iter()
        .filter_map(|v| serde_json::from_value(v.clone()).ok())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn roundtrip(json: &str) {
        let v: serde_json::Value = serde_json::from_str(json).unwrap();
        let item: Item = serde_json::from_value(v.clone()).expect("deserialize");
        let back = serde_json::to_value(&item).expect("serialize");
        assert_eq!(v, back, "roundtrip mismatch for {json}");
    }
    #[test] fn arrow() { roundtrip(r##"{"type":"arrow","p1":[1.0,2.0],"p2":[3.0,4.0],"color":"#ff0000ff","width":4,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn line() { roundtrip(r##"{"type":"line","p1":[1.0,2.0],"p2":[3.0,4.0],"color":"#00ff00ff","width":2,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn rect_no_fill() { roundtrip(r##"{"type":"rect","rect":[0.0,0.0,10.0,20.0],"color":"#112233ff","width":3,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn rect_with_fill() { roundtrip(r##"{"type":"rect","rect":[0.0,0.0,10.0,20.0],"color":"#112233ff","width":3,"fill":"#445566ff","pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn ellipse() { roundtrip(r##"{"type":"ellipse","rect":[0.0,0.0,10.0,20.0],"color":"#112233ff","width":3,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn highlight() { roundtrip(r##"{"type":"highlight","rect":[0.0,0.0,60.0,20.0],"color":"#ffe000","pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn freehand() { roundtrip(r##"{"type":"freehand","points":[[1.0,2.0],[3.0,4.0],[5.0,6.0]],"color":"#000000ff","width":2,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn text() { roundtrip(r##"{"type":"text","text":"hi","color":"#ffffffff","family":"Sans","point_size":24,"bold":true,"text_width":-1.0,"align":"left","pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn step() { roundtrip(r##"{"type":"step","number":3,"color":"#3b82f6ff","radius":16.0,"pos":[5.0,5.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn pixelate() { roundtrip(r##"{"type":"pixelate","rect":[20.0,20.0,60.0,40.0],"block":14,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn blur() { roundtrip(r##"{"type":"blur","rect":[20.0,20.0,60.0,40.0],"radius":12,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"##); }
    #[test] fn rotation_geometry_preserved() { roundtrip(r##"{"type":"rect","rect":[0.0,0.0,10.0,20.0],"color":"#112233ff","width":3,"pos":[-12.625,7.0625],"rotation":33.7,"origin":[53.05,21.35]}"##); }
}
