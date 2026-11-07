"""Face filtering (#6): offline, local-only, keep only the chosen people."""

import ast
import csv
import io
import json
import os
import stat
import tempfile
import unittest

from tests.face_helpers import (
    DAD,
    ME,
    ME_AGAIN,
    ME_BLURRY,
    MOM,
    STRANGER,
    VECTORS,
    FakeEngine,
    NetworkUsed,
    no_network,
    save_photo,
    save_video,
)
from tests.helpers import snapshot
from travelphotos import output
from travelphotos.faces import cluster, evaluate, matching, pipeline
from travelphotos.faces.store import FaceStore, StoreError
from travelphotos.server import AppState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "travelphotos")


def make_trip(folder: str) -> None:
    save_photo(os.path.join(folder, "a_me.jpg"), ME)
    save_photo(os.path.join(folder, "b_mom.jpg"), MOM)
    save_photo(os.path.join(folder, "c_group.jpg"), STRANGER, ME_AGAIN, STRANGER)  # me among strangers
    save_photo(os.path.join(folder, "d_stranger.jpg"), STRANGER)
    save_photo(os.path.join(folder, "e_landscape.jpg"))
    save_photo(os.path.join(folder, "f_blurry.jpg"), ME_BLURRY)
    save_photo(os.path.join(folder, "g_dad.jpg"), DAD)
    save_video(os.path.join(folder, "h_mom_clip.mp4"), {MOM: (3.0, 4.0)})
    save_video(os.path.join(folder, "i_empty_clip.mp4"), {})
    with open(os.path.join(folder, "j_broken.jpg"), "wb") as fh:
        fh.write(b"not really a jpeg")


class Trip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inp = os.path.join(self.tmp.name, "trip")
        self.data = os.path.join(self.tmp.name, "data")
        make_trip(self.inp)
        self.engine = FakeEngine()
        self.state = AppState(self.inp, data_dir=self.data, face_engine_factory=lambda: self.engine)

    def save_person(self, name, colour):
        refs = os.path.join(self.tmp.name, "refs-" + name)
        save_photo(os.path.join(refs, "1.jpg"), colour)
        save_photo(os.path.join(refs, "2.jpg"), None)  # no face: skipped
        info = self.state.face_action("reference", {"name": name, "folder": refs})["reference"]
        self.assertEqual(info["used"], ["1.jpg"])
        self.assertEqual(info["skipped"], ["2.jpg"])
        return next(p["id"] for p in self.state.faces.to_json()["people"] if p["name"] == name)

    def run_flow(self, names, interval=1.0):
        self.state.do_scan(self.inp, "", "")
        ids = {"本人": self.save_person("本人", ME), "媽媽": self.save_person("媽媽", MOM), "爸爸": self.save_person("爸爸", DAD)}
        self.state.face_action("analyze", {"interval": interval})
        self.state.face_action("select", {"person_ids": [ids[n] for n in names], "enabled": True})
        return self.state.faces.decisions


class OfflineFlowTests(Trip):
    def test_whole_flow_works_with_network_blocked(self):
        before = snapshot(self.inp)
        out = os.path.join(self.tmp.name, "out")
        with no_network():
            self.run_flow(["本人"])
            summary = output.apply(self.state.scan, self.state.result, out, face_filter=self.state.faces.output_filter())
        written = sorted(n for n in os.listdir(out) if not n.startswith(".") and not n.startswith("report"))
        self.assertEqual(
            sorted(n.split("_", 1)[1] for n in written),
            sorted(["a_me.jpg", "c_group.jpg", "f_blurry.jpg", "j_broken.jpg"]),
        )
        self.assertEqual(summary["face_excluded"], 6)
        self.assertEqual(snapshot(self.inp), before, "original files must not change")

    def test_no_network_helper_really_blocks(self):
        import socket

        with no_network(), self.assertRaises(NetworkUsed):
            socket.create_connection(("example.com", 80), timeout=1)


class DecisionTests(Trip):
    def reasons(self, decisions):
        return {fid: (d.keep, d.status, d.reason) for fid, d in decisions.items()}

    def test_one_person(self):
        d = self.run_flow(["本人"])
        self.assertTrue(d["a_me.jpg"].keep)
        self.assertEqual(d["a_me.jpg"].reason, "偵測到：本人")
        self.assertFalse(d["b_mom.jpg"].keep)
        self.assertTrue(d["c_group.jpg"].keep, "group photo with strangers is kept")
        self.assertFalse(d["d_stranger.jpg"].keep)
        self.assertIn("未偵測到指定人物", d["d_stranger.jpg"].reason)
        self.assertFalse(d["e_landscape.jpg"].keep)
        self.assertIn("沒有偵測到人臉", d["e_landscape.jpg"].reason)
        self.assertFalse(d["g_dad.jpg"].keep, "a saved but unselected person is not 'uncertain'")
        self.assertFalse(d["h_mom_clip.mp4"].keep)

    def test_unsure_face_is_kept_and_marked(self):
        d = self.run_flow(["本人"])
        self.assertTrue(d["f_blurry.jpg"].keep)
        self.assertEqual(d["f_blurry.jpg"].status, matching.UNCERTAIN_KEEP)
        self.assertEqual(d["f_blurry.jpg"].label, "保留（不確定）")
        self.assertIn("可能是 本人", d["f_blurry.jpg"].reason)

    def test_unreadable_file_is_kept_as_uncertain(self):
        d = self.run_flow(["本人"])
        self.assertTrue(d["j_broken.jpg"].keep)
        self.assertEqual(d["j_broken.jpg"].status, matching.UNREADABLE_KEEP)

    def test_any_of_several_people(self):
        d = self.run_flow(["本人", "媽媽"])
        kept = sorted(fid for fid, x in d.items() if x.keep and x.status == matching.MATCH_KEEP)
        self.assertEqual(kept, ["a_me.jpg", "b_mom.jpg", "c_group.jpg", "h_mom_clip.mp4"])

    def test_video_kept_when_a_sampled_frame_shows_the_person(self):
        d = self.run_flow(["媽媽"], interval=1.0)
        self.assertTrue(d["h_mom_clip.mp4"].keep)
        self.assertEqual(d["h_mom_clip.mp4"].reason, "偵測到：媽媽")
        self.assertFalse(d["i_empty_clip.mp4"].keep)
        hits = [h for h in self.state.faces.hits if h.file_id == "h_mom_clip.mp4"]
        self.assertEqual([h.frame for h in hits], [3.0])

    def test_sampling_interval_is_used(self):
        d = self.run_flow(["媽媽"], interval=5.0)  # samples at 0 s and 5 s only
        self.assertFalse(d["h_mom_clip.mp4"].keep)
        self.assertEqual(self.state.faces.analysis["h_mom_clip.mp4"].samples, 2)

    def test_bad_interval(self):
        self.state.do_scan(self.inp, "", "")
        for bad in (0, -1, "x", 10_000):
            with self.assertRaises(ValueError):
                self.state.face_action("analyze", {"interval": bad})


class OutputTests(Trip):
    def test_report_lists_kept_and_excluded_with_reasons(self):
        self.run_flow(["本人"])
        out = os.path.join(self.tmp.name, "out")
        output.apply(self.state.scan, self.state.result, out, face_filter=self.state.faces.output_filter())
        with open(os.path.join(out, output.REPORT_CSV), encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        by_file = {r["原始檔案"]: r for r in rows}
        self.assertEqual(len(by_file), 10)
        self.assertEqual(by_file["a_me.jpg"]["人物篩選"], "保留：偵測到：本人")
        self.assertTrue(by_file["a_me.jpg"]["新檔名"])
        self.assertEqual(by_file["d_stranger.jpg"]["新檔名"], "")
        self.assertIn("排除：未偵測到指定人物", by_file["d_stranger.jpg"]["人物篩選"])
        self.assertIn("沒有偵測到人臉", by_file["e_landscape.jpg"]["人物篩選"])
        self.assertTrue(by_file["f_blurry.jpg"]["人物篩選"].startswith("保留（不確定）"))
        kept_positions = sorted(int(r["新順序"]) for r in rows if r["新順序"])
        self.assertEqual(kept_positions, [1, 2, 3, 4])
        with open(os.path.join(out, output.REPORT_JSON), encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(report["face_filter"]["people"], ["本人"])
        self.assertEqual(len(report["face_filter"]["excluded"]), 6)

    def test_without_filter_everything_is_written(self):
        self.run_flow(["本人"])
        self.state.face_action("select", {"person_ids": self.state.faces.to_json()["selected"], "enabled": False})
        self.assertIsNone(self.state.faces.output_filter())
        out = os.path.join(self.tmp.name, "out")
        summary = output.apply(self.state.scan, self.state.result, out, face_filter=self.state.faces.output_filter())
        self.assertEqual(summary["written"], 10)

    def test_filter_on_without_people_or_analysis_is_refused(self):
        self.state.do_scan(self.inp, "", "")
        self.state.face_action("select", {"person_ids": [], "enabled": True})
        with self.assertRaisesRegex(ValueError, "還沒偵測人臉"):
            self.state.faces.output_filter()
        self.state.face_action("analyze", {"interval": 2})
        with self.assertRaisesRegex(ValueError, "還沒選要保留的人"):
            self.state.faces.output_filter()

    def test_rescan_resets_the_face_step(self):
        self.run_flow(["本人"])
        self.state.do_scan(self.inp, "", "")
        self.assertIsNone(self.state.faces.analysis)
        self.assertFalse(self.state.faces.enabled)


class ClusterTests(Trip):
    def test_faces_are_grouped_and_a_group_can_be_saved(self):
        self.state.do_scan(self.inp, "", "")
        self.state.face_action("analyze", {"interval": 1})
        clusters = self.state.faces.to_json()["clusters"]
        self.assertEqual((clusters[0]["faces"], clusters[0]["files"]), (3, 2))  # the stranger, twice in the group photo
        groups = {}
        for c in self.state.faces.clusters:
            groups[c.id] = sorted({self.state.faces.hits[i].file_id for i in c.members})
        mom = next(cid for cid, files in groups.items() if files == ["b_mom.jpg", "h_mom_clip.mp4"])
        name = self.state.face_action("save-cluster", {"cluster_id": mom, "name": "媽媽"})["saved"]
        self.assertEqual(name, "媽媽")
        person = self.state.faces.store.people[0]
        self.state.face_action("select", {"person_ids": [person.id], "enabled": True})
        kept = sorted(f for f, d in self.state.faces.decisions.items() if d.status == matching.MATCH_KEEP)
        self.assertEqual(kept, ["b_mom.jpg", "h_mom_clip.mp4"])
        # The same group is now recognised by name.
        data = self.state.faces.to_json()
        self.assertEqual(next(c for c in data["clusters"] if c["id"] == mom)["person"], "媽媽")

    def test_cluster_function(self):
        vecs = [VECTORS[ME], VECTORS[MOM], VECTORS[ME_AGAIN], VECTORS[ME], VECTORS[STRANGER]]
        groups = cluster.cluster_faces(vecs)
        self.assertEqual(groups[0].members, [0, 2, 3])
        self.assertEqual(sorted(len(g.members) for g in groups), [1, 1, 3])
        self.assertEqual(cluster.cluster_faces([]), [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "data", "faces.json")

    def test_people_persist_between_runs(self):
        s = FaceStore(self.path)
        p = s.add_embeddings("本人", [VECTORS[ME]])
        again = FaceStore(self.path)
        self.assertEqual([(x.id, x.name, len(x.embeddings)) for x in again.people], [(p.id, "本人", 1)])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_rename_remove_and_duplicates(self):
        s = FaceStore(self.path)
        p = s.add_embeddings("本人", [VECTORS[ME]])
        with self.assertRaises(StoreError):
            s.add_embeddings("本人", [VECTORS[ME]])
        with self.assertRaises(StoreError):
            s.add_embeddings("  ", [VECTORS[ME]])
        s.add_embeddings("", [VECTORS[ME_AGAIN]], person_id=p.id)
        self.assertEqual(len(s.get(p.id).embeddings), 2)
        s.rename(p.id, "我")
        self.assertEqual(FaceStore(self.path).people[0].name, "我")
        s.remove(p.id)
        self.assertEqual(FaceStore(self.path).people, [])

    def test_delete_all_removes_the_file(self):
        s = FaceStore(self.path)
        s.add_embeddings("本人", [VECTORS[ME]])
        self.assertTrue(os.path.isfile(self.path))
        self.assertTrue(s.delete_all())
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(FaceStore(self.path).people, [])

    def test_damaged_file_is_reported_and_can_still_be_deleted(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            fh.write("{broken")
        with self.assertRaises(StoreError):
            FaceStore(self.path)
        state = AppState("", data_dir=os.path.dirname(self.path), face_engine_factory=FakeEngine)
        self.assertIn("無法讀取人臉資料檔", state.faces.to_json()["message"])
        self.assertTrue(state.face_action("delete-all", {})["deleted"])
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(state.faces.to_json()["message"], "")


class DeleteButtonTests(Trip):
    def test_delete_all_clears_saved_and_in_memory_face_data(self):
        self.run_flow(["本人"])
        path = os.path.join(self.data, "faces.json")
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(self.state.face_action("delete-all", {})["deleted"])
        self.assertFalse(os.path.exists(path))
        data = self.state.faces.to_json()
        self.assertEqual(data["people"], [])
        self.assertFalse(data["analyzed"])
        self.assertEqual(self.state.faces.hits, [])


class AccuracyTests(Trip):
    def test_labelled_set_reports_accuracy(self):
        labels = os.path.join(self.tmp.name, "labels.csv")
        with open(labels, "w", encoding="utf-8") as fh:
            fh.write("檔案,人物\n")
            fh.write("a_me.jpg,本人\nb_mom.jpg,媽媽\nc_group.jpg,本人\nd_stranger.jpg,\ne_landscape.jpg,\n")
            fh.write("g_dad.jpg,爸爸\nh_mom_clip.mp4,媽媽\ni_empty_clip.mp4,\n")
        store = FaceStore(os.path.join(self.tmp.name, "eval", "faces.json"))
        store.add_embeddings("本人", [VECTORS[ME]])
        store.add_embeddings("媽媽", [VECTORS[MOM]])
        store.add_embeddings("爸爸", [VECTORS[DAD]])
        out = io.StringIO()
        report = os.path.join(self.tmp.name, "accuracy.csv")
        with no_network():
            code = evaluate.main(
                ["--photos", self.inp, "--labels", labels, "--people", "本人,媽媽", "--interval", "1", "--report", report],
                engine=FakeEngine(),
                store=store,
                out=out,
            )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("準確率：100.0%（8/8）", text)
        with open(report, encoding="utf-8-sig") as fh:
            self.assertIn("準確率：100.0%", fh.read())

    def test_mistakes_lower_the_accuracy(self):
        d = {
            "a": matching.Decision(True, matching.MATCH_KEEP, ""),
            "b": matching.Decision(True, matching.MATCH_KEEP, ""),
            "c": matching.Decision(False, matching.OTHERS, ""),
            "d": matching.Decision(False, matching.NO_FACES, ""),
        }
        ev = evaluate.evaluate(d, {"a": {"本人"}, "b": set(), "c": {"本人"}, "d": set()}, {"本人"})
        self.assertEqual((ev.total, ev.correct, ev.false_keep, ev.missed), (4, 2, 1, 1))
        self.assertAlmostEqual(ev.accuracy, 0.5)
        self.assertAlmostEqual(ev.precision, 0.5)
        self.assertAlmostEqual(ev.recall, 0.5)


class NoNetworkInFacePathTests(unittest.TestCase):
    """The whole travelphotos package, including faces/, has no network client code."""

    NETWORK_MODULES = {"socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "websocket", "asyncio"}
    ALLOWED = {("server.py", "http.server"), ("server.py", "http"), ("server.py", "urllib.parse")}

    def test_no_network_imports_anywhere_in_the_package(self):
        checked = 0
        for root, _dirs, files in os.walk(PKG):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, PKG).replace(os.sep, "/")
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), rel)
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        mods = [node.module]
                    for mod in mods:
                        if (rel, mod) in self.ALLOWED:
                            continue
                        self.assertNotIn(mod.split(".")[0], self.NETWORK_MODULES, f"{rel} imports {mod}")
                checked += 1
        self.assertGreater(checked, 10)
        self.assertTrue(os.path.isfile(os.path.join(PKG, "faces", "engine.py")))


if __name__ == "__main__":
    unittest.main()
