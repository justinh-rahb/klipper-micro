cmake_minimum_required(VERSION 3.16)
project(klipper_micro_native_tests C)

find_package(ZLIB REQUIRED)

add_executable(native_tests
    test_native.c
    ../../main/klipper_protocol.c
    ../../main/klipper_dictionary.c
    ../../main/klipper_clocksync.c
)
target_include_directories(native_tests PRIVATE ../../main)
target_link_libraries(native_tests PRIVATE ZLIB::ZLIB m)
target_compile_options(native_tests PRIVATE -Wall -Wextra -Werror -Wpedantic)

enable_testing()
add_test(NAME native_tests COMMAND native_tests)
