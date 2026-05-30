# Rib Probe — small-feature gradient regression test (spec track)

A throwaway probe part, NOT a real benchmark: an 80x40x5 mm plate carrying 12 small
ribs (2x4x6 mm) in a 6x2 GridLocations pattern. It exists to regression-test the
small-feature-precision fix (iou_res): a 1mm shift of the rib pattern should score
materially below a perfect reconstruction (was ~0.992 at iou_res=24 — no gradient;
~0.90 at iou_res=64 — usable gradient).
