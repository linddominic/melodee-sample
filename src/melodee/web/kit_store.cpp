// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Kerem Kilic (Ellic Studio)
#include "melodee/web/kit_store.h"
#include "melodee/engine/engine_info.h"
#include "melodee/model/print.h"
#include "melodee/model/project_file.h"
#include "melodee/shell/mpc_program.h"
#include "melodee/shell/mpc_project.h"
#include "melodee/shell/project_kits.h"
#include "melodee/web/card_files.h"
#include <fcntl.h>
#include <unistd.h>
#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <memory>
#include <vector>

namespace melodee::web {
namespace fs = std::filesystem;
namespace {
constexpr const char* json_type = "application/json; charset=utf-8";
constexpr uint64_t room_margin = uint64_t(8) << 20; // as web_app.cpp keeps back
constexpr size_t list_limit = 1000;                 // kits listed at most

Reply fail(int status, const std::string& words) { return {status, json_type, "{\"error\":" + json_text(words) + "}"}; }
Reply ok(const std::string& json) { return {200, json_type, json}; }

std::string lowered(std::string text) {
    for (auto& c : text) c = char(std::tolower(static_cast<unsigned char>(c)));
    return text;
}
std::string extension_of(const fs::path& path) { return lowered(path.extension().string()); }
bool starts(const std::string& text, const char* head) { return text.compare(0, std::strlen(head), head) == 0; }
bool ends(const std::string& text, const std::string& tail) {
    return text.size() >= tail.size() && !text.compare(text.size() - tail.size(), tail.size(), tail);
}

// What the sampler reads (shell/sample_decode.cpp), and what a browser may be handed to play.
bool sampler_reads(const fs::path& path) {
    auto e = extension_of(path);
    return e == ".wav" || e == ".aif" || e == ".aiff" || e == ".flac" || e == ".ogg" || e == ".oga" || e == ".mp3";
}

// Whether `inside` is `root` or under it, both as they really are.
bool under(const std::string& root, const fs::path& inside) {
    if (root.empty()) return false;
    std::error_code e;
    auto r = fs::weakly_canonical(root, e);
    if (e) return false;
    auto i = fs::weakly_canonical(inside, e);
    if (e) return false;
    auto a = r.begin(), b = i.begin();
    for (; a != r.end(); ++a, ++b) {
        if (a->empty()) continue;
        if (b == i.end() || *a != *b) return false;
    }
    return true;
}

std::vector<uint8_t> read_file(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    return std::vector<uint8_t>(std::istreambuf_iterator<char>(file), {});
}

// A kit file read whole: the project, its patterns and what else a save must carry.
struct Loaded {
    std::unique_ptr<Project> project = std::make_unique<Project>();
    std::unique_ptr<PatternBank> patterns = std::make_unique<PatternBank>();
    std::array<std::vector<uint8_t>, max_plugins> states;
    PrintTable prints;
};

// An .xpj as the Project list's Load does it (ProjectStore import_mpc()), an .mldp as Load reads it.
std::string read_kit(const fs::path& path, Loaded& out) {
    const auto kind = extension_of(path);
    if (kind != ".xpj" && kind != ".mldp") return "Not a kit";
    auto bytes = read_file(path);
    if (bytes.empty()) return "Could not read it";
    if (kind == ".xpj") {
        MpcImport report;
        auto error = import_mpc_project(bytes, path.string(), *out.project, *out.patterns, report);
        if (error.empty()) layers_from_programs(*out.project);
        return error;
    }
    unsigned version = 0;
    auto error = load_project(bytes, *out.project, *out.patterns, &version, &out.states, &out.prints);
    if (error.empty()) for (auto& t : out.project->tracks) upgrade_params(t.engine, version, t.params); // as Load does
    return error;
}

// The kit a kit file is about: Load kit's (the first kit with a sample on a pad), else its first kit track (an
// empty kit made here), else -1.
int kit_of(const Project& project) {
    int k = kit_track(project);
    if (k >= 0) return k;
    for (unsigned t = 0; t < track_count; ++t) if (project.tracks[t].engine == EngineKind::Sampler) return int(t);
    return -1;
}

// `bytes` into `path` through a hidden file beside it, flushed, then renamed over it: a pulled card or a full one
// leaves the file as it was. 0 on success, else the status to answer with.
int write_whole(const fs::path& path, const std::vector<uint8_t>& bytes, std::string& error) {
    std::error_code e;
    const auto folder = path.parent_path();
    auto space = fs::space(folder, e);
    if (e || space.available < bytes.size() + room_margin) { error = "The SD card is full"; return 507; }
    const auto temp = folder / ("." + path.filename().string() + ".part");
    int fd = ::open(temp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) { error = "Could not write to the SD card"; return 500; }
    bool good = true;
    for (size_t at = 0; good && at < bytes.size();) {
        ssize_t n = ::write(fd, bytes.data() + at, bytes.size() - at);
        good = n > 0;
        if (good) at += size_t(n);
    }
    good = good && ::fsync(fd) == 0;
    good = ::close(fd) == 0 && good;
    if (good) fs::rename(temp, path, e);
    if (!good || e) { fs::remove(temp, e); error = "Could not write to the SD card"; return 500; }
    return 0;
}

int save_kit(const fs::path& path, const Loaded& kit, std::string& error) {
    return write_whole(path, save_project(*kit.project, *kit.patterns, &kit.states, &kit.prints), error);
}

// A project's own folders beside it (shell/project_store.cpp): they go where it goes.
constexpr const char* project_folders[] {" Loops", " Prints"};
fs::path folder_of(const fs::path& project, const char* tail) { return project.parent_path() / (project.stem().string() + tail); }

// The id's file: "factory:<rel>" under the factory projects, "sd:<rel>" under the card.
bool kit_place(const KitRoots& roots, const std::string& id, fs::path& out, bool& factory, std::string& error) {
    factory = starts(id, "factory:");
    const bool sd = starts(id, "sd:");
    if (!factory && !sd) { error = "No such kit"; return false; }
    const std::string& root = factory ? roots.factory : roots.card;
    if (root.empty()) { error = factory ? "No factory kits here" : "No SD card in the MPC, or it is mounted on a computer"; return false; }
    if (!card_place(root, id.substr(factory ? 8 : 3), out, error)) return false;
    std::error_code e;
    if (!fs::is_regular_file(out, e)) { error = "No such kit"; return false; }
    return true;
}

// A sample id's file: "factory:<rel>" under the factory samples, "sd:<rel>" under the card.
bool sample_place(const KitRoots& roots, const std::string& id, fs::path& out, std::string& error) {
    const bool factory = starts(id, "factory:"), sd = starts(id, "sd:");
    if (!factory && !sd) { error = "No such sample"; return false; }
    const std::string& root = factory ? roots.factory_samples : roots.card;
    if (root.empty()) { error = factory ? "No factory samples here" : "No SD card in the MPC, or it is mounted on a computer"; return false; }
    return card_place(root, id.substr(factory ? 8 : 3), out, error);
}

std::string id_of(const KitRoots& roots, const fs::path& path, bool factory) {
    const auto root = fs::path(factory ? roots.factory : roots.card);
    return (factory ? "factory:" : "sd:") + path.lexically_relative(root).generic_string();
}

// A sample's place as the page shows it: "SD/Samples/Kick.wav", "Factory/Projects/Kits/...", else as it is.
std::string shown_path(const KitRoots& roots, const std::string& path) {
    auto inside = [&](const std::string& root) {
        return !root.empty() && path.size() > root.size() && !path.compare(0, root.size(), root) && path[root.size()] == '/';
    };
    if (inside(roots.card)) return "SD" + path.substr(roots.card.size());
    if (inside(roots.factory)) return "Factory/Projects" + path.substr(roots.factory.size());
    if (inside(roots.factory_samples)) return "Factory/Samples" + path.substr(roots.factory_samples.size());
    return path;
}

// A layer's file: the instrument's file for "<file>#<which>".
std::string file_of(const SampleRef& ref) {
    std::string path = ref.path, file, which;
    return split_program_pad(path, file, which) ? file : path;
}
bool plain_file(const SampleRef& ref) { return std::strchr(ref.path, '#') == nullptr && !ref.instrument(); }
bool present(const SampleRef& ref) {
    std::error_code e;
    return fs::exists(file_of(ref), e);
}
// Whether the browser may be sent the file: an audio file on the card or the factory drive.
bool previewable(const KitRoots& roots, const SampleRef& ref) {
    if (!ref.used() || !plain_file(ref) || !sampler_reads(ref.path)) return false;
    std::error_code e;
    if (!fs::is_regular_file(ref.path, e)) return false;
    return under(roots.card, ref.path) || under(roots.factory, ref.path) || under(roots.factory_samples, ref.path);
}

const char* play_name(PadPlay p) { return p == PadPlay::Gate ? "gate" : "oneshot"; }

std::string layer_json(const KitRoots& roots, const Project& project, uint16_t slot, unsigned n) {
    const auto& ref = project.samples[slot % sample_slots];
    const bool there = ref.used() && present(ref);
    std::string kind = !ref.used() ? "none" : plain_file(ref) ? "file" : "instrument";
    return "{\"index\":" + std::to_string(n) + ",\"sampleId\":\"slot:" + std::to_string(slot % sample_slots) + "\""
        + ",\"sampleName\":" + json_text(ref.name) + ",\"samplePath\":" + json_text(shown_path(roots, ref.path))
        + ",\"kind\":" + json_text(kind) + ",\"missing\":" + (there ? "false" : "true")
        + ",\"preview\":" + (previewable(roots, ref) ? "true" : "false") + "}";
}

std::string pad_json(const KitRoots& roots, const Project& project, const Track& track, unsigned n) {
    const PadSound& pad = track.pads[n];
    char label[4];
    pad_label(n, label);
    std::string layers;
    unsigned count = 0;
    for (unsigned l = 0; l < pad_layers; ++l) {
        auto layer = pad.layer(l);
        if (!layer.used()) continue;
        layers += (count++ ? "," : "") + layer_json(roots, project, layer.sample, l);
    }
    const auto& own = project.samples[pad.sample % sample_slots];
    return "{\"index\":" + std::to_string(n) + ",\"label\":\"" + label + "\",\"name\":" + json_text(own.name)
        + ",\"level\":" + std::to_string(pad.level) + ",\"pan\":" + std::to_string(pad.pan)
        + ",\"pitch\":" + std::to_string(pad.pitch) + ",\"fine\":" + std::to_string(pad.fine)
        + ",\"play\":\"" + play_name(pad.play) + "\",\"start\":" + std::to_string(pad.start) + ",\"end\":" + std::to_string(pad.end)
        + ",\"group\":" + std::to_string(pad.group) + ",\"reverse\":" + (pad.reverse ? "true" : "false")
        + ",\"filter\":" + json_text(pad_filter_name(pad.filter)) + ",\"layerPlay\":" + json_text(layer_play_name(pad.layer_play))
        + ",\"muted\":" + (track.pad_muted(n) ? "true" : "false") + ",\"layers\":[" + layers + "]}";
}

// Pads with a sound, and banks with one, in the kit.
void count_pads(const Track& track, unsigned& pads, unsigned& banks) {
    pads = banks = 0;
    for (unsigned b = 0; b < sampler_banks; ++b) {
        unsigned here = 0;
        for (unsigned k = 0; k < 16; ++k) here += track.pads[b * 16 + k].used();
        pads += here;
        banks += here > 0;
    }
}

// The project Melodee's project list opened last, or opens at start (Melodee/settings): an edit here could be
// written over by the MPC's next save of it.
bool open_on_mpc(const KitRoots& roots, const fs::path& path) {
    if (roots.card.empty()) return false;
    std::ifstream file(fs::path(roots.card) / "Melodee" / "settings");
    std::string line;
    while (std::getline(file, line))
        if ((starts(line, "last=") && line.substr(5) == path.string()) || (starts(line, "start=") && line.substr(6) == path.string())) return true;
    return false;
}

// A slot of `project` for the file at `path`: the one that has it, else a free one (cleared), else -1.
int slot_for(Project& project, const std::string& path, const std::string& name) {
    int free = -1;
    for (unsigned n = 0; n < sample_slots; ++n) {
        if (project.samples[n].used() && path == project.samples[n].path) return int(n);
        if (free < 0 && !project.samples[n].used()) free = int(n);
    }
    if (free < 0 || path.size() >= sizeof(SampleRef::path)) return -1;
    auto& ref = project.samples[size_t(free)];
    ref = SampleRef {};
    std::snprintf(ref.path, sizeof(ref.path), "%s", path.c_str());
    std::snprintf(ref.name, sizeof(ref.name), "%s", name.c_str());
    project.chops[size_t(free)] = SampleChop {};
    return free;
}

// Slots no pad plays any more, let go (with their chops), so a kit edited for long does not run out.
void free_unplayed(Project& project) {
    for (unsigned s = 0; s < sample_slots; ++s) {
        if (!project.samples[s].used()) continue;
        bool played = false;
        for (const auto& t : project.tracks)
            for (const auto& p : t.pads) played = played || (p.used() && p.plays(uint16_t(s)));
        if (!played) { project.samples[s] = SampleRef {}; project.chops[s] = SampleChop {}; }
    }
}

void name_kit(Project& project, int track, const std::string& name) {
    std::snprintf(project.name, sizeof(project.name), "%s", name.c_str());
    if (track >= 0) project.tracks[size_t(track)].set_name(name.c_str());
}

bool number(const std::map<std::string, std::string>& values, const char* key, int low, int high, int& out) {
    auto found = values.find(key);
    if (found == values.end() || found->second.empty()) return false;
    char* end = nullptr;
    long v = std::strtol(found->second.c_str(), &end, 10);
    if (*end) return false;
    out = int(std::clamp<long>(v, low, high));
    return true;
}

std::string text_of(const std::map<std::string, std::string>& values, const char* key) {
    auto found = values.find(key);
    return found == values.end() ? std::string() : found->second;
}
} // namespace

KitRoots kit_roots(const std::string& card) {
    const char* factory = std::getenv("MELODEE_FACTORY_PROJECTS");
    const char* samples = std::getenv("MELODEE_FACTORY_SAMPLES");
    return {card, factory ? factory : "/content/Projects", samples ? samples : "/content/Samples"};
}

bool kit_editable(const std::string& id) {
    const std::string head = std::string("sd:") + kits_folder + "/";
    return starts(id, head.c_str()) && id.size() > head.size() && lowered(fs::path(id).extension().string()) == ".mldp";
}

std::string kit_file_name(const std::string& name) {
    std::string trimmed = name;
    while (!trimmed.empty() && std::isspace(static_cast<unsigned char>(trimmed.back()))) trimmed.pop_back();
    size_t first = 0;
    while (first < trimmed.size() && std::isspace(static_cast<unsigned char>(trimmed[first]))) ++first;
    trimmed = trimmed.substr(first);
    if (trimmed.empty() || trimmed.size() >= name_length) return {}; // a track's name holds 23
    return safe_name(trimmed + ".mldp", ".mldp");
}

const KitStore::Summary& KitStore::summary_of(const fs::path& path) {
    std::error_code e;
    const auto size = fs::file_size(path, e);
    const auto time = fs::last_write_time(path, e);
    auto& entry = seen[path.string()];
    if (!entry.summary.name.empty() && entry.size == size && entry.time == time) return entry.summary;
    entry.size = size;
    entry.time = time;
    entry.summary = Summary {};
    entry.summary.name = path.stem().string();
    Loaded kit;
    entry.summary.error = read_kit(path, kit);
    if (entry.summary.error.empty()) {
        int k = kit_track(*kit.project);
        entry.summary.kit = k >= 0;
        int t = kit_of(*kit.project);
        if (t >= 0) count_pads(kit.project->tracks[size_t(t)], entry.summary.pads, entry.summary.banks);
    }
    return entry.summary;
}

namespace {
std::string summary_json(const std::string& id, const std::string& folder, const std::string& format, bool factory, bool editable,
                         const std::string& name, const std::string& error, bool kit, unsigned pads, unsigned banks) {
    return "{\"id\":" + json_text(id) + ",\"name\":" + json_text(name) + ",\"source\":\"" + (factory ? "factory" : "sd")
        + "\",\"format\":\"" + format + "\",\"readOnly\":" + (editable ? "false" : "true")
        + ",\"padCount\":" + std::to_string(pads) + ",\"bankCount\":" + std::to_string(banks)
        + ",\"kit\":" + (kit ? "true" : "false") + ",\"folder\":" + json_text(folder)
        + (error.empty() ? std::string() : ",\"error\":" + json_text(error));
}

// Kit files under `dir`, `depth` folders down: .xpj and .mldp, but not a project's own folders.
void find_kits(const fs::path& dir, int depth, std::vector<fs::path>& out) {
    std::error_code e;
    std::vector<fs::path> here;
    for (const auto& item : fs::directory_iterator(dir, e)) here.push_back(item.path());
    std::sort(here.begin(), here.end());
    for (const auto& path : here) {
        if (out.size() >= list_limit) return;
        const auto name = path.filename().string();
        if (name.empty() || name[0] == '.' || name == "System Volume Information") continue;
        std::error_code f;
        if (fs::is_directory(path, f)) {
            if (depth <= 0 || ends(name, "_[ProjectData]") || ends(name, " Loops") || ends(name, " Prints")) continue;
            find_kits(path, depth - 1, out);
        } else {
            auto kind = extension_of(path);
            if (kind == ".xpj" || kind == ".mldp") out.push_back(path);
        }
    }
}
} // namespace

Reply KitStore::list(const KitRoots& roots) {
    std::string out = "{\"card\":" + std::string(roots.card.empty() ? "false" : "true") + ",\"kits\":[";
    bool first = true;
    auto add = [&](const fs::path& root, const fs::path& path, bool factory) {
        const auto& s = summary_of(path);
        auto id = id_of(roots, path, factory);
        auto folder = path.parent_path().lexically_relative(root).generic_string();
        out += (first ? "" : ",") + summary_json(id, folder, extension_of(path).substr(1), factory, !factory && kit_editable(id),
                                                 s.name, s.error, s.kit, s.pads, s.banks) + "}";
        first = false;
    };
    std::vector<fs::path> found;
    if (!roots.factory.empty())
        for (const char* folder : {"Kits", "Demos"}) {
            found.clear();
            find_kits(fs::path(roots.factory) / folder, 2, found);
            for (const auto& p : found) add(roots.factory, p, true);
        }
    if (!roots.card.empty())
        for (const char* folder : {"Melodee/Projects", "MPC-Sample/Projects"}) {
            found.clear();
            find_kits(fs::path(roots.card) / folder, 4, found);
            for (const auto& p : found) add(roots.card, p, false);
        }
    return ok(out + "]}");
}

Reply KitStore::detail(const KitRoots& roots, const std::string& id) {
    fs::path path;
    bool factory = false;
    std::string error;
    if (!kit_place(roots, id, path, factory, error)) return fail(404, error);
    Loaded kit;
    error = read_kit(path, kit);
    if (!error.empty()) return fail(422, error);
    const Project& project = *kit.project;
    const int t = kit_of(project);
    unsigned pads = 0, banks = 0;
    if (t >= 0) count_pads(project.tracks[size_t(t)], pads, banks);
    const bool editable = !factory && kit_editable(id);
    const auto root = fs::path(factory ? roots.factory : roots.card);
    std::string out = summary_json(id, path.parent_path().lexically_relative(root).generic_string(), extension_of(path).substr(1), factory,
                                   editable, path.stem().string(), {}, kit_track(project) >= 0, pads, banks);
    std::string warnings;
    unsigned missing = 0;
    std::string banks_json;
    if (t >= 0) {
        const Track& track = project.tracks[size_t(t)];
        out += ",\"track\":" + json_text(track.name);
        for (unsigned b = 0; b < sampler_banks; ++b) {
            std::string list;
            unsigned count = 0;
            for (unsigned k = 0; k < 16; ++k) {
                const unsigned n = b * 16 + k;
                if (!track.pads[n].used()) continue;
                for (unsigned l = 0; l < pad_layers; ++l) {
                    auto layer = track.pads[n].layer(l);
                    if (layer.used() && !(project.samples[layer.sample % sample_slots].used() && present(project.samples[layer.sample % sample_slots]))) ++missing;
                }
                list += (count++ ? "," : "") + pad_json(roots, project, track, n);
            }
            banks_json += (b ? "," : "") + std::string("{\"index\":") + std::to_string(b) + ",\"name\":\"" + char('A' + b) + "\",\"pads\":[" + list + "]}";
        }
    } else {
        warnings += json_text("No kit track in this project");
    }
    if (missing) warnings += (warnings.empty() ? "" : ",") + json_text(std::to_string(missing) + (missing == 1 ? " sample is" : " samples are") + " missing");
    if (t >= 0 && kit_track(project) < 0) warnings += (warnings.empty() ? "" : ",") + json_text("No pads yet: Load kit needs at least one");
    if (editable && open_on_mpc(roots, path)) warnings += (warnings.empty() ? "" : ",") + json_text("Open on the MPC: saving it there writes over changes made here");
    out += ",\"open\":" + std::string(editable && open_on_mpc(roots, path) ? "true" : "false");
    out += ",\"warnings\":[" + warnings + "],\"banks\":[" + banks_json + "]}";
    return ok(out);
}

namespace {
// Melodee/Projects/Kits on the card, made when missing; false with `error` when there is no card.
bool kits_dir(const KitRoots& roots, fs::path& out, std::string& error) {
    if (roots.card.empty()) { error = "No SD card in the MPC, or it is mounted on a computer"; return false; }
    out = fs::path(roots.card) / kits_folder;
    std::error_code e;
    fs::create_directories(out, e);
    if (!fs::is_directory(out, e)) { error = "Could not write to the SD card"; return false; }
    return true;
}
} // namespace

Reply KitStore::create(const KitRoots& roots, const std::string& name) {
    auto file = kit_file_name(name);
    if (file.empty()) return fail(400, "Name the kit (at most 23 characters, no / or leading dot)");
    fs::path dir;
    std::string error;
    if (!kits_dir(roots, dir, error)) return fail(409, error);
    const auto path = free_path(dir, file);
    Loaded kit;
    starting_project(*kit.project, *kit.patterns); // Melodee's own new project: one empty kit on track 1
    name_kit(*kit.project, 0, path.stem().string());
    if (int status = save_kit(path, kit, error)) return fail(status, error);
    return detail(roots, id_of(roots, path, false));
}

Reply KitStore::duplicate(const KitRoots& roots, const std::string& id, const std::string& name) {
    fs::path from;
    bool factory = false;
    std::string error;
    if (!kit_place(roots, id, from, factory, error)) return fail(404, error);
    Loaded source;
    error = read_kit(from, source);
    if (!error.empty()) return fail(422, error);
    const int k = kit_track(*source.project);
    if (k < 0) return fail(422, "No kit in " + from.stem().string());
    std::string wanted = name.empty() ? from.stem().string() + " copy" : name;
    if (wanted.size() >= name_length) wanted = wanted.substr(0, name_length - 1);
    auto file = kit_file_name(wanted);
    if (file.empty()) return fail(400, "Name the kit (at most 23 characters, no / or leading dot)");
    fs::path dir;
    if (!kits_dir(roots, dir, error)) return fail(409, error);
    const auto path = free_path(dir, file);
    Loaded kit;
    starting_project(*kit.project, *kit.patterns);
    Project& into = *kit.project;
    // Load kit's own import (shell/project_kits.h): the pads, their layers, effects and the kit's values; the files
    // stay where they are (a factory kit's on the internal drive), each named by its path.
    import_kit(*source.project, unsigned(k), into.tracks[0], [&](const SampleRef& ref) {
        int slot = slot_for(into, ref.path, ref.name);
        if (slot >= 0) { into.samples[size_t(slot)].frames = ref.frames; into.samples[size_t(slot)].zones = ref.zones; }
        return slot;
    });
    name_kit(into, 0, path.stem().string());
    if (int status = save_kit(path, kit, error)) return fail(status, error);
    return detail(roots, id_of(roots, path, false));
}

Reply KitStore::rename(const KitRoots& roots, const std::string& id, const std::string& name) {
    if (!kit_editable(id)) return fail(403, "Only kits in " + std::string(kits_folder) + " can be renamed here");
    fs::path path;
    bool factory = false;
    std::string error;
    if (!kit_place(roots, id, path, factory, error)) return fail(404, error);
    auto file = kit_file_name(name);
    if (file.empty()) return fail(400, "Name the kit (at most 23 characters, no / or leading dot)");
    const auto target = path.parent_path() / file;
    std::error_code e;
    if (target == path) return detail(roots, id);
    const bool case_only = lowered(target.string()) == lowered(path.string()); // FAT: the same file
    if (!case_only && fs::exists(target, e)) return fail(409, "A kit has that name");
    Loaded kit;
    error = read_kit(path, kit);
    if (!error.empty()) return fail(422, error);
    name_kit(*kit.project, kit_of(*kit.project), target.stem().string());
    if (case_only) {
        fs::rename(path, path.parent_path() / ".melodee-rename.mldp", e);
        if (e) return fail(500, "Could not rename it");
        if (int status = save_kit(target, kit, error)) { fs::rename(path.parent_path() / ".melodee-rename.mldp", path, e); return fail(status, error); }
        fs::remove(path.parent_path() / ".melodee-rename.mldp", e);
    } else {
        if (int status = save_kit(target, kit, error)) return fail(status, error);
        fs::remove(path, e);
        for (const char* tail : project_folders) fs::rename(folder_of(path, tail), folder_of(target, tail), e);
    }
    return detail(roots, id_of(roots, target, false));
}

Reply KitStore::remove(const KitRoots& roots, const std::string& id) {
    if (!kit_editable(id)) return fail(403, "Only kits in " + std::string(kits_folder) + " can be deleted here");
    fs::path path;
    bool factory = false;
    std::string error;
    if (!kit_place(roots, id, path, factory, error)) return fail(404, error);
    std::error_code e;
    fs::remove(path, e);
    if (e) return fail(500, "Could not delete it");
    for (const char* tail : project_folders) fs::remove_all(folder_of(path, tail), e);
    ::sync();
    seen.erase(path.string());
    return ok("{}");
}

Reply KitStore::set_pad(const KitRoots& roots, const std::string& id, const std::map<std::string, std::string>& values) {
    if (!kit_editable(id)) return fail(403, "Factory kits and other projects are read only: duplicate it to edit");
    fs::path path;
    bool factory = false;
    std::string error;
    if (!kit_place(roots, id, path, factory, error)) return fail(404, error);
    int n = -1;
    if (!number(values, "pad", -1, int(sampler_pads), n) || n < 0 || n >= int(sampler_pads)) return fail(400, "No such pad");
    Loaded kit;
    error = read_kit(path, kit);
    if (!error.empty()) return fail(422, error);
    Project& project = *kit.project;
    const int t = kit_of(project);
    if (t < 0) return fail(422, "No kit track in this project");
    Track& track = project.tracks[size_t(t)];
    PadSound& pad = track.pads[size_t(n)];
    if (text_of(values, "clear") == "1") {
        pad = PadSound {};
        track.pad_fx.at[size_t(n)] = Chain {{}, pad_slots};
        track.set_pad_muted(unsigned(n), false);
        clear_trims(track.zone_trims, unsigned(n));
    }
    if (auto sample = text_of(values, "sample"); !sample.empty()) {
        fs::path file;
        if (!sample_place(roots, sample, file, error)) return fail(404, error);
        std::error_code e;
        if (!fs::is_regular_file(file, e)) return fail(404, "No such sample");
        if (!sampler_reads(file)) return fail(415, "Not a sample Melodee plays (WAV, AIFF, FLAC, Ogg or MP3)");
        if (file.string().size() >= sizeof(SampleRef::path)) return fail(400, "The sample's path is too long for a kit");
        free_unplayed(project); // room first: the slots no pad plays any more
        const bool fresh = !pad.used(); // a pad that had a sound keeps its values (level, tune, envelope...)
        // The slot the pad played, let go when only this pad played it, so a full kit can still swap a sample.
        if (pad.used()) {
            unsigned others = 0;
            for (const auto& tr : project.tracks)
                for (const auto& p : tr.pads) others += p.used() && p.plays(pad.sample);
            if (others == 1 && !pad.layered()) { project.samples[pad.sample % sample_slots] = SampleRef {}; pad.sample = no_sample; }
        }
        int slot = slot_for(project, file.string(), file.stem().string());
        if (slot < 0) return fail(409, "The kit holds 64 samples: clear a pad first");
        if (fresh) pad = PadSound {};
        pad.sample = uint16_t(slot);
        pad.start = pad.end = 0; pad.loop_start = 0; // the new file's whole length
        pad.layers = {};
        pad.low_velocity = 1; pad.high_velocity = 127;
        pad.layer_play = LayerPlay::Velocity;
        pad.own_tempo = 0; pad.beats = 0; pad.gain = 0;
        clear_trims(track.zone_trims, unsigned(n));
    }
    int v = 0;
    if (pad.used()) {
        if (number(values, "level", 0, 127, v)) pad.level = uint8_t(v);
        if (number(values, "pan", -50, 50, v)) pad.pan = int8_t(v);
        if (number(values, "pitch", -48, 48, v)) pad.pitch = int8_t(v);
        if (number(values, "fine", -99, 99, v)) pad.fine = int8_t(v);
        auto play = text_of(values, "play");
        if (play == "oneshot") pad.play = PadPlay::OneShot;
        else if (play == "gate") pad.play = PadPlay::Gate;
    }
    free_unplayed(project);
    if (int status = save_kit(path, kit, error)) return fail(status, error);
    return detail(roots, id);
}

Reply KitStore::pad_audio(const KitRoots& roots, const std::string& id, int pad, int layer) {
    fs::path path;
    bool factory = false;
    std::string error;
    if (!kit_place(roots, id, path, factory, error)) return fail(404, error);
    if (pad < 0 || pad >= int(sampler_pads) || layer < 0 || layer >= int(pad_layers)) return fail(400, "No such pad");
    Loaded kit;
    error = read_kit(path, kit);
    if (!error.empty()) return fail(422, error);
    const int t = kit_of(*kit.project);
    if (t < 0) return fail(404, "No kit track in this project");
    auto l = kit.project->tracks[size_t(t)].pads[size_t(pad)].layer(unsigned(layer));
    if (!l.used()) return fail(404, "Nothing on this pad");
    const auto& ref = kit.project->samples[l.sample % sample_slots];
    if (!ref.used() || !present(ref)) return fail(404, "The sample is missing");
    if (!previewable(roots, ref)) return fail(415, "No preview for this sample in the browser");
    return {200, file_type(fs::path(ref.path).filename().string()), {}, ref.path, {}};
}

Reply KitStore::sample_audio(const KitRoots& roots, const std::string& sample) {
    fs::path file;
    std::string error;
    if (!sample_place(roots, sample, file, error)) return fail(404, error);
    std::error_code e;
    if (!fs::is_regular_file(file, e)) return fail(404, "No such sample");
    if (!sampler_reads(file)) return fail(415, "Not an audio file");
    return {200, file_type(file.filename().string()), {}, file.string(), {}};
}

Reply KitStore::samples(const KitRoots& roots, const std::string& source, const std::string& rel) {
    if (source != "sd" && source != "factory") return fail(400, "No such place");
    const std::string& root = source == "sd" ? roots.card : roots.factory_samples;
    if (root.empty()) return fail(409, source == "sd" ? "No SD card in the MPC, or it is mounted on a computer" : "No factory samples here");
    fs::path folder;
    std::string error;
    if (!card_place(root, rel, folder, error)) return fail(404, error);
    std::error_code e;
    if (!fs::is_directory(folder, e)) return fail(404, "Not a folder");
    return ok("{\"source\":" + json_text(source) + ",\"path\":" + json_text(rel) + ",\"entries\":" + folder_json(folder, source == "sd" && rel.empty()) + "}");
}

} // namespace melodee::web
