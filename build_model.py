"""
Rebuild erc4337-userop-risk-scorer.onnx deterministically.

Constraints from the OpenGradient hub:
  - No weight initializers (public inference rejects models with embedded weights).
  - Pure ops only: Relu, ReduceSum, Sigmoid.
  - Input shape must be rank >= 2, so we use [1, N].
  - opset 11 — in opset 13 ReduceSum's `axes` moved from attribute to input.
"""

import onnx
from onnx import TensorProto, helper

OUTPUT_PATH = "erc4337-userop-risk-scorer.onnx"
NUM_FEATURES = 10

features = helper.make_tensor_value_info(
    "features", TensorProto.FLOAT, [1, NUM_FEATURES]
)
userop_risk_probability = helper.make_tensor_value_info(
    "userop_risk_probability", TensorProto.FLOAT, [1, 1]
)

nodes = [
    helper.make_node("Relu", ["features"], ["h1"], name="relu1"),
    helper.make_node(
        "ReduceSum", ["h1"], ["h2"], name="rs1", axes=[1], keepdims=1
    ),
    helper.make_node(
        "Sigmoid", ["h2"], ["userop_risk_probability"], name="sig1"
    ),
]

graph = helper.make_graph(
    nodes,
    "erc4337_userop_risk_graph",
    [features],
    [userop_risk_probability],
)

model = helper.make_model(
    graph,
    producer_name="cryptoyasenka",
    producer_version="1.00",
    opset_imports=[helper.make_opsetid("", 11)],
)
model.ir_version = 7

onnx.checker.check_model(model)
onnx.save(model, OUTPUT_PATH)
print(f"wrote {OUTPUT_PATH}")
