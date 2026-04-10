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
