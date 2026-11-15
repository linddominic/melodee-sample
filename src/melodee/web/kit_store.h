// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Kerem Kilic (Ellic Studio)
#pragma once
#include "melodee/web/web_server.h"
#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

// The web page's Kits tab (docs/KIT_MANAGER.md): the MPC's factory kits and
// the kits on the card, read with Melodee's own readers (an .xpj through
// shell/mpc_project.h, an .mldp through model/project_file.h) into one
// Project and described from its first kit (shell/project_kits.h
// kit_track(), the kit Load kit takes). Kits of one's own are .mldp files in
// the card's Melodee/Projects/Kits, made with starting_project() and
// import_kit() and written with save_project(), so the MPC's Project list
// shows them and Load kit loads them. Nothing else is ever written: factory
// kits, stock .xpj projects and other Melodee projects are read only here.
//
// A kit is named by an id the page sends back: "factory:<path under the
// factory projects folder>" or "sd:<path under the card>"; a sample by
// "factory:<path under the factory samples>" or "sd:<path under the card>".
// Every one is resolved with card_place() (web/card_files.h) under its own
// root, so no browser path reaches anything else.
//
// Runs on the web page's thread (one request at a time), never on the audio
// or MIDI threads; the project in play is never touched.
namespace melodee::web {

struct KitRoots {
    std::string card;            // the card's top while it is home; empty: no card
    std::string factory;         // the factory projects: /content/Projects ($MELODEE_FACTORY_PROJECTS)
    std::string factory_samples; // the factory samples: /content/Samples ($MELODEE_FACTORY_SAMPLES)
};
KitRoots kit_roots(const std::string& card);

// The card folder kits are made in, relative to the card.
constexpr const char* kits_folder = "Melodee/Projects/Kits";

class KitStore {
public:
    // GET: {"card", "kits":[summary...]}, factory first, then the card's, by name.
    // Kits not read yet once `budget_ms` has gone come with "pending": true and no counts, and "pending" counts them;
    // a budget below 0 reads every one.
    Reply list(const KitRoots& roots, int budget_ms = -1);
    // GET: a summary and its banks, each used pad with its values and layers.
    Reply detail(const KitRoots& roots, const std::string& id);
    // POST: a new kit in Melodee/Projects/Kits; empty or a duplicate of `from`.
    Reply create(const KitRoots& roots, const std::string& name);
    Reply duplicate(const KitRoots& roots, const std::string& id, const std::string& name);
    // POST, kits in Melodee/Projects/Kits only.
    Reply rename(const KitRoots& roots, const std::string& id, const std::string& name);
    Reply remove(const KitRoots& roots, const std::string& id);
    // POST: pad 0-127 of the kit. `values`: "sample" (an id), "clear", "level", "pan", "pitch", "fine", "play".
    Reply set_pad(const KitRoots& roots, const std::string& id, const std::map<std::string, std::string>& values);
    // GET: a pad layer's file, as it is, when the browser can play it; a sample by id.
    Reply pad_audio(const KitRoots& roots, const std::string& id, int pad, int layer);
    Reply sample_audio(const KitRoots& roots, const std::string& sample);
    // GET: a folder of samples to pick from: source "sd" or "factory", `rel` under it.
    Reply samples(const KitRoots& roots, const std::string& source, const std::string& rel);
    // GET: every sound under a source, for a search: {"source", "files":[rel...], "sizes":[bytes...], "full"} (full: the limit was reached).
    Reply sounds(const KitRoots& roots, const std::string& source);

private:
    struct Summary {
        std::string name, error;
        unsigned pads = 0, banks = 0;
        bool kit = false;
    };
    struct Seen {
        uintmax_t size = 0;
        std::filesystem::file_time_type time {};
        Summary summary;
    };
    // The file's summary, read now when `read`, else only when it was read before and has not changed since.
    const Summary* summary_of(const std::filesystem::path& path, bool read);
    std::map<std::string, Seen> seen; // by path: a file is read once while it stays the same
    // A kit file as read: the parts of its details that the file alone decides, and each pad layer's audio reply
    // (pad * pad_layers + layer). Kept for the last few kits while their files stay the same; a factory kit's also
    // on the card (Melodee/.cache), so it is read once at all.
    struct Parsed {
        std::string key, path;
        std::string head, warnings, banks;
        std::vector<Reply> replies;
    };
    const Parsed* reading(const KitRoots& roots, const std::string& id, const std::filesystem::path& path, bool factory, Reply& failure);
    static std::string cache_key(const std::filesystem::path& path, uintmax_t size, std::filesystem::file_time_type time);
    // A kit written here: what was read of it is read again.
    void forget(const std::filesystem::path& path);
    std::vector<Parsed> parsed;
    // The kits' summaries on the card (Melodee/.cache/kit-summaries), read at the first listing, written when one is complete.
    void load_summaries(const KitRoots& roots);
    void save_summaries(const KitRoots& roots);
    std::string summaries_from = "\n"; // the card they were read from (none yet)
    bool summaries_dirty = false;
};

// The pure parts, for the tests.
// Whether a kit id names something the Kits tab may change: an .mldp in Melodee/Projects/Kits.
bool kit_editable(const std::string& id);
// A name typed for a kit as the name of its file, ".mldp" added; empty when the card would not take it.
std::string kit_file_name(const std::string& name);

} // namespace melodee::web
