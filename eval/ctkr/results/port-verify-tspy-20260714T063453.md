# Port-verification §6 experiment — cross-language TS↔Python

- **spec (S)** = `ss:7bd32e13d6a22b42fdde8fcd` (ts, 448 seedable members)
- **port (S')** = `ss:4c95bb440785eee8be744167` (py, 1990 seedable members)
- role view = `similarity`  ·  17 roles · 67 provided exports · 29 composition ops
- seeds = self-index hom-profiles (depth-1, dim 30); §6.2 normalization applied at seed time when ON
- **ungated** (§6.3 / §7.2): this measures the cross-language bias, it does not assert a port passes.

## Normalization ON/OFF delta

| §7 gate | OFF | ON (§6.2) | delta |
|---|---|---|---|
| role coverage | 52.9% | 58.8% | ▲ +5.9 pts |
| interface preservation | 6.0% | 7.5% | ▲ +1.5 pts |
| composition preservation | 20.7% | 31.0% | ▲ +10.3 pts |
| fidelity | 66.0% | 61.4% | ▼ -4.6 pts |
| cycle consistency | 19.4% | 13.4% | ▼ -6.0 pts |

- forward functor: OFF mapped 139/448; ON mapped 119/448
- punch list length: OFF 96, ON 91

## Punch list — normalization ON (first 12)
```
# Port verification — MetaCoding / ss:7bd32e13d6a22b42fdde8fcd
normalization: on (v1)   passedAtCeiling: false

## Gates
  ✗  role coverage                58.8%  (floor 0.9, ceiling 1)  — 10/17 tier-I role classes covered
  ✗  interface preservation        7.5%  (floor 0.9, ceiling 1)  — 5/67 provided exports preserved
  ✗  composition preservation     31.0%  (floor 0.8, ceiling 1)  — 9/29 composition ops realizable (9/28 protocol ops)
  ✗  fidelity                     61.4%  (floor 0.8, ceiling 0.95)  — 78/127 internal edges preserved
  ✗  cycle consistency            13.4%  (floor 0.8, ceiling 0.9)  — G(F(s))=s on 0.134 of mapped pairs

## Punch list (12 items)
  [blocker] role-coverage → roles[role_id=role:21f44f1e52fef3e7f0a5f5fa]
      role class "homProfileBySymbolId" (cardinality 1) has NO member mapped into the port — the port dropped this role
      · src/ctkr/artifacts.ts::CtkrHandleImpl::homProfileBySymbolId (role homProfileBySymbolId)
  [blocker] role-coverage → roles[role_id=role:335af6deab6eb7349bd8ed0d]
      role class "edgeKinds" (cardinality 1) has NO member mapped into the port — the port dropped this role
      · src/ctkr/artifacts.ts::CtkrHandle::motifs::edgeKinds (role edgeKinds)
  [blocker] role-coverage → roles[role_id=role:6bb2b6a8b154d814344de149]
      role class "patternIdsWithEvidenceInRepo" (cardinality 1) has NO member mapped into the port — the port dropped this role
      · src/ctkr/artifacts.ts::CtkrHandle::patternIdsWithEvidenceInRepo (role patternIdsWithEvidenceInRepo)
  [blocker] role-coverage → roles[role_id=role:7422b14c44464870b6bcaf40]
      role class "close" (cardinality 1) has NO member mapped into the port — the port dropped this role
      · src/ctkr/artifacts.ts::CtkrHandleImpl::close (role close)
  [blocker] role-coverage → roles[role_id=role:85b1b523f97b1980b2044fc4]
      role class "NNLabelRow" (cardinality 1) has NO member mapped into the port — the port dropped this role
      · src/ctkr/types.ts::NNLabelRow (role NNLabelRow)
  [blocker] role-coverage → roles[role_id=role:9fc9e4ec5523c2459764cd73]
      role class "topK1" (cardinality 63) has NO member mapped into the port — the port dropped this role
      · src/ctkr/artifacts.test.ts::topK1 (role topK1)
  [blocker] role-coverage → roles[role_id=role:dfbdcc3520975dacc5010eb3]
      role class "repo1" (cardinality 2) has NO member mapped into the port — the port dropped this role
      · src/ctkr/artifacts.ts::repo1 (role repo1)
  [blocker] interface-preservation → interface.provides[symbol=src/ctkr/types.ts::MotifRow::motif_id]
      provided export "src/ctkr/types.ts::MotifRow::motif_id" (modes REFERENCES) has no image in the port — the export was lost
      · src/ctkr/types.ts::MotifRow::motif_id
  [blocker] interface-preservation → interface.provides[symbol=src/ctkr/types.ts::MotifRow::support]
      provided export "src/ctkr/types.ts::MotifRow::support" (modes REFERENCES) has no image in the port — the export was lost
      · src/ctkr/types.ts::MotifRow::support
  [blocker] interface-preservation → interface.provides[symbol=src/ctkr/artifacts.ts::openCtkrArtifacts]
      provided export "src/ctkr/artifacts.ts::openCtkrArtifacts" (modes REFERENCES) has no image in the port — the export was lost
      · src/ctkr/artifacts.ts::openCtkrArtifacts
  [blocker] interface-preservation → interface.provides[symbol=src/ctkr/types.ts::EvidenceRow]
      provided export "src/ctkr/types.ts::EvidenceRow" (modes CONSTRUCTS) has no image in the port — the export was lost
      · src/ctkr/types.ts::EvidenceRow
  [blocker] interface-preservation → interface.provides[symbol=src/ctkr/artifacts.ts::CtkrHandle::nearestByVector::typeLiteral3::k]
      provided export "src/ctkr/artifacts.ts::CtkrHandle::nearestByVector::typeLiteral3::k" (modes REFERENCES) has no image in the port — the export was lost
      · src/ctkr/artifacts.ts::CtkrHandle::nearestByVector::typeLiteral3::k
```
