// SPDX-License-Identifier: AGPL-3.0-only
// The Kits tab's store (src/melodee/web/kit_store.h), driven from tests/test_kit_store.py:
//   kit_store CARD FACTORY FACTORY_SAMPLES ACTION [key=value...]
// prints the reply's status on the first line and its body (or the file it sends) after it.
#include "melodee/web/kit_store.h"
#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>

using namespace melodee::web;

int main(int argc, char** argv) {
    if (argc < 5) { std::fprintf(stderr, "usage: kit_store CARD FACTORY FACTORY_SAMPLES ACTION [key=value...]\n"); return 2; }
    KitRoots roots {argv[1], argv[2], argv[3]};
    if (roots.card == "-") roots.card.clear(); // no card
    const std::string action = argv[4];
    std::map<std::string, std::string> q;
    for (int n = 5; n < argc; ++n) {
        std::string pair = argv[n];
        auto eq = pair.find('=');
        q[pair.substr(0, eq)] = eq == std::string::npos ? std::string() : pair.substr(eq + 1);
    }
    KitStore store;
    Reply r;
    if (action == "list") r = store.list(roots);
    else if (action == "list-quick") r = store.list(roots, 0); // with no time to read: only what is known
    else if (action == "list-twice") { // with no time to read: all pending; then read, by the same store as the server keeps it
        Reply quick = store.list(roots, 0);
        r = store.list(roots);
        Reply after = store.list(roots, 0);
        std::printf("%d\n{\"quick\":%s,\"full\":%s,\"after\":%s}\n", r.status, quick.body.c_str(), r.body.c_str(), after.body.c_str());
        return 0;
    }
    else if (action == "detail") r = store.detail(roots, q["id"]);
    else if (action == "create") r = store.create(roots, q["name"]);
    else if (action == "duplicate") r = store.duplicate(roots, q["id"], q["name"]);
    else if (action == "rename") r = store.rename(roots, q["id"], q["name"]);
    else if (action == "delete") r = store.remove(roots, q["id"]);
    else if (action == "pad") { auto id = q["id"]; q.erase("id"); r = store.set_pad(roots, id, q); }
    else if (action == "audio") r = store.pad_audio(roots, q["id"], std::atoi(q["pad"].c_str()), std::atoi(q["layer"].c_str()));
    else if (action == "sample") r = store.sample_audio(roots, q["sample"]);
    else if (action == "replay") { // a pad played, given another sample and played again, by one store as the server keeps it
        const int pad = std::atoi(q["pad"].c_str());
        Reply before = store.pad_audio(roots, q["id"], pad, 0);
        Reply set = store.set_pad(roots, q["id"], {{"pad", q["pad"]}, {"sample", q["sample"]}});
        Reply after = store.pad_audio(roots, q["id"], pad, 0);
        std::printf("%d\n{\"before\":\"%s\",\"set\":%d,\"after\":\"%s\"}\n", after.status, before.file.c_str(), set.status, after.file.c_str());
        return 0;
    }
    else if (action == "samples") r = store.samples(roots, q["source"], q["path"]);
    else if (action == "sounds") r = store.sounds(roots, q["source"]);
    else if (action == "names") { // the pure helpers
        std::printf("200\n{\"editable\":%s,\"file\":\"%s\"}\n", kit_editable(q["id"]) ? "true" : "false", kit_file_name(q["name"]).c_str());
        return 0;
    } else { std::fprintf(stderr, "unknown action\n"); return 2; }
    std::printf("%d\n", r.status);
    if (!r.file.empty()) std::printf("{\"file\":\"%s\",\"type\":\"%s\"}\n", r.file.c_str(), r.type.c_str());
    else std::printf("%s\n", r.body.c_str());
    return 0;
}
