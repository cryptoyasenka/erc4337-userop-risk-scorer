# ERC-4337 UserOp Risk Scorer

ONNX model that scores an ERC-4337 `UserOperation` on its probability of being malicious or economically abusive before a bundler includes it in a bundle. Designed for smart-account wallets, bundler services (Pimlico, Alchemy, Stackup, Biconomy), and security middlewares that need a fast pre-inclusion risk gate.

## Overview

Ethereum is in the middle of the biggest wallet-architecture shift since EOAs: **account abstraction**. ERC-4337 (live on mainnet since 2023) and EIP-7702 (shipping in Pectra) make it possible for any address to act like a smart account — with session keys, sponsored gas, batched calls, and arbitrary signature schemes. That flexibility is also a new attack surface:

- A malicious `paymaster` can silently drain sponsorship budgets by front-loading expensive reverts.
- A compromised session key can push `UserOperation`s that look legitimate at signature-level but target dangerous calldata.
- A rogue `bundler` can collude with a sender to censor or reorder ops.
- Address poisoning and `initCode` spoofing let attackers trick wallets into deploying to unintended factories.

Classical wallet risk models score *EOAs* and *tokens*. None of them understand `UserOperation` semantics — the object that actually gets signed in an AA wallet. This model fills that gap. It takes 10 numerical features that describe the UserOp, its sender, its paymaster, its target, and the bundler route, and returns a single `userop_risk_probability ∈ [0, 1]`.

The model is deliberately tiny (pure ONNX, ~250 bytes, 3 ops) so it can run inside a wallet extension, a bundler's pre-validation hook, or an on-chain verifiable inference runtime like OpenGradient's TEE without adding measurable latency to the sign-and-send flow.

## Architecture

Pure ONNX graph, opset 11, **no weight initializers** (the OpenGradient hub rejects models with embedded weights for public inference):

```
features [1,10] float32
      │
     Relu
      │
  ReduceSum(axes=[1], keepdims=1)
      │
    Sigmoid
      │
userop_risk_probability [1,1] float32
```

Because there are no trained weights, the model behaves as a monotone scoring function: the sum of the non‑negative normalized features squashed through a sigmoid. All risk logic lives in **how you normalize the inputs** before inference — every feature must already be in a `[0, 1]`‑ish range where "1 = maximally risky". The Scoring Pillars below describe the normalization contract.

## Scoring Pillars

| Pillar | Weight | Features |
|--------|--------|----------|
| **Sender Provenance** | 25% | `sender_age_days`, `sender_op_history` |
| **Paymaster / Sponsorship** | 25% | `paymaster_reputation`, `sponsor_ratio` |
| **Calldata & Target** | 30% | `calldata_entropy`, `target_contract_risk`, `gas_limit_ratio` |
| **Mempool Behavior** | 20% | `nonce_gap`, `init_code_present`, `bundler_diversity` |

Callers are expected to scale each feature before inference so its contribution matches the pillar weight — e.g. `paymaster_reputation = unknown_ratio * 0.25 / 2`.

## Input Schema

`features: float32 [1, 10]`

All features are expected to be pre-normalized into a `[0, 1]` range where `1 = maximally risky`. Callers are responsible for the normalization contract described in the "Scoring Pillars" section below.

| Index | Name | Meaning |
|---|---|---|
| 0 | `sender_age_days` | Inverse age of the smart account (new = risky). `1 = age < 1h`, `0 = age > 1y` |
| 1 | `sender_op_history` | Inverse of historical UserOp count from this sender (cold = risky) |
| 2 | `paymaster_reputation` | Inverse reputation of the paymaster (`0 = well-known`, `1 = new/unknown`) |
| 3 | `sponsor_ratio` | Fraction of gas covered by the paymaster (`1.0 = fully sponsored`, higher ratios → more abuse risk) |
| 4 | `calldata_entropy` | Shannon entropy of the calldata, scaled. High = obfuscated/packed exploit calldata |
| 5 | `target_contract_risk` | Risk score of the primary target contract (unverified, very new, flagged) |
| 6 | `gas_limit_ratio` | `callGasLimit` vs typical for this contract class, clipped (`>>1` = suspicious overspend) |
| 7 | `nonce_gap` | Gap between sender's expected and submitted nonce. `0 = in-order`, `1 = large out-of-order` |
| 8 | `init_code_present` | `1` if `initCode` is non-empty (first-time wallet deployment), else `0` |
| 9 | `bundler_diversity` | How frequently this sender rotates across different bundlers (`1 = every op via a new one` → suspicious) |

## Output Schema

`userop_risk_probability: float32 [1, 1]`

A single probability in `[0, 1]`. Higher values mean the UserOperation is more likely to be malicious, abusive, or economically irrational for the sponsor.

| Range | Grade | Action |
|---|---|---|
| 0.00 – 0.20 | A | Accept — include in next bundle |
| 0.20 – 0.40 | B | Accept with monitoring — log for paymaster analytics |
| 0.40 – 0.60 | C | Hold — require extra signature / step-up auth |
| 0.60 – 0.80 | D | Reject from sponsored path — force user to pay own gas |
| 0.80 – 1.00 | F | Block — drop from mempool, alert the sender's wallet |

## Flags

| Flag | Trigger | Severity |
|---|---|---|
| F1 | `sponsor_ratio = 1.0` and `paymaster_reputation > 0.7` | High — abuse of an unknown paymaster |
| F2 | `calldata_entropy > 0.8` and `target_contract_risk > 0.5` | High — obfuscated call into a shady target |
| F3 | `gas_limit_ratio > 0.8` | Medium — gas griefing pattern |
| F4 | `init_code_present = 1` and `sender_op_history > 0.9` | Medium — re-deployment from an inactive smart account |
| F5 | `bundler_diversity > 0.8` and `nonce_gap > 0.5` | Medium — censorship evasion / reorder attempt |
| F6 | `userop_risk_probability > 0.8` | Critical — block from the sponsored path |

## Use Cases

1. **Smart-account wallets** (Safe, Rabby AA, Coinbase Smart Wallet, Ambire) — score every UserOp before the user signs and surface a human-readable warning.
2. **Bundler services** (Pimlico, Alchemy Rundler, Stackup, Biconomy) — run as a pre-`simulateValidation` hook to drop obviously malicious ops before paying the simulation gas.
3. **Paymasters** — gate sponsorship on the score so that unknown senders can't drain the sponsorship budget with reverts.
4. **AA security middleware** (Blockaid, Webacy, Harpie for AA) — plug into the RPC layer as a pre-submit filter.

## Data Sources

- **UserOp history:** ERC-4337 EntryPoint logs (`UserOperationEvent`, `AccountDeployed`) via Etherscan, Dune, or a node RPC.
- **Paymaster reputation:** aggregated on-chain sponsorship history + curated lists from Pimlico / Stackup.
- **Target contract risk:** Blockaid, GoPlus, Harpie, or local heuristic scoring.
- **Bundler routing:** AA-specific explorers (jiffyscan.xyz, blockscan.com/aa).
