# WebXR drone's-eye view (P11) - manual steps

What is built (and unit-tested without a headset): `viewer/src/xr.js` + `viewer/src/rig.js`.
`renderer.xr` is enabled, a `VRButton` sits in the HUD, the camera lives in a dolly group that rides the selected
drone with smoothed position and heading, and controllers can grab buildings.
What cannot be checked on a Mac and needs a human: entering an immersive session. Use the **Immersive Web Emulator**.

## Controls inside XR
| Input | Action |
|-------|--------|
| *Enter VR* button (HUD, left panel) | start the session; the rig snaps to drone 0 and follows it |
| squeeze / grip, **right** controller | next airborne drone |
| squeeze / grip, **left** controller | previous airborne drone |
| trigger (select) pointing at a building | grab it (it follows the controller); release to drop |
| release | `edit_building` is sent with the new x,y (size unchanged, snapped to 1 m). Rejected edits snap back and toast the reason |

## Steps with the Immersive Web Emulator (Chrome, Windows laptop)
1. Install **Immersive Web Emulator** (Meta) from the Chrome Web Store (Brave usually works; use Chrome if the tab does not appear).
2. **Sanity check the emulator first** on three.js's own example, https://threejs.org/examples/#webxr_xr_dragging :
   open DevTools (F12) -> the **Immersive Web Emulator** tab -> pick *Meta Quest 3* -> press **Enter VR** on the page.
   If this does not work the browser/extension is the problem, not AeroSwarm.
3. Start AeroSwarm: `scripts\windows\demo.ps1 -NoBrowser`, then open `http://127.0.0.1:8080` in the same Chrome
   (localhost counts as a secure context, which WebXR requires).
4. DevTools -> Immersive Web Emulator -> choose the device, then click **ENTER VR** in the left HUD panel.
5. Ride a drone: in the emulator's controller panel press the right controller's **grip/squeeze** to cycle drones.
   The view should glide with the drone (no jumps; heading follows the flight direction).
6. Grab a building: aim the emulated controller ray at a building, press **trigger** (select), move, release.
   Expect either the building ends up where you dropped it (after a short "settling wind..." period) or a toast
   with the rejection reason and the building snaps back (e.g. dropping onto a depot).
7. Exit with the *EXIT VR* button or the emulator's exit control; the desktop orbit camera must come back.

## Checklist to tick (also in `TESTING_CHECKLIST_WINDOWS.md`)
- [ ] emulator works on `webxr_xr_dragging`
- [ ] *ENTER VR* appears in the AeroSwarm HUD and starts a session
- [ ] rig rides drone 0, smooth, heading follows; grip cycles next/previous
- [ ] grab + move + release a building -> accepted or rejected with a toast
- [ ] exiting VR restores the desktop view

## If something is off
| Symptom | Likely cause / fix |
|---------|-------------------|
| HUD says "VR NOT SUPPORTED" | no WebXR in this browser/profile, or the emulator is off: enable the extension, reload, try Chrome |
| Emulator tab missing in DevTools | page does not expose `navigator.xr` yet: reload with DevTools open; test on threejs.org first |
| Grabbed building jumps / wrong place | only x,y are used; z of the controller is ignored by design. Check `grabToBuilding` in `viewer/src/editor-logic.js` (unit-tested) |
| Motion feels jerky | tune `tau`/`headingTau` in `viewer/src/rig.js` (`DroneRig`, unit-tested: monotone, no overshoot) |

## Headless verification already done on the Mac
`viewer` builds; `npm test` runs `tests/rig.test.js` (smoothing, shortest-way heading, drone cycling) and
`tests/editor-logic.test.js` (grab/transform maths); the built page loads in a browser, the XR button reports
"VR NOT SUPPORTED" where WebXR is absent (expected on a desktop browser without the emulator).
