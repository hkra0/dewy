#pragma once
#include <stdint.h>

namespace maintenance {
// Independent of Arduino so the exact trial acceptance policy can run on a host.
struct BootHealth {
    static constexpr uint32_t StableMs=30000;
    static constexpr uint32_t DeadlineMs=120000;
    uint32_t started=0, lastLoop=0, loops=0;
    bool ready(uint32_t now) const {
        return uint32_t(now-started)>=StableMs && loops>=100 && uint32_t(now-lastLoop)<2000;
    }
    const char* failure(uint32_t now) const {
        if(uint32_t(now-started)<DeadlineMs) return "";
        if(!loops) return "setup_incomplete";
        if(uint32_t(now-lastLoop)>=2000) return "main_loop_stalled";
        return "confirmation_timeout";
    }
};
}
