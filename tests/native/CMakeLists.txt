cmake_minimum_required(VERSION 3.16)
project(klipper_micro_native_tests C)

find_package(ZLIB REQUIRED)

add_executable(native_tests
    test_native.c
    ../../src/klipper_protocol.c
    ../../src/klipper_dictionary.c
    ../../src/klipper_clocksync.c
    ../../src/heater_control.c
)
target_include_directories(native_tests PRIVATE ../../src)
target_link_libraries(native_tests PRIVATE ZLIB::ZLIB m)
target_compile_options(native_tests PRIVATE -Wall -Wextra -Werror -Wpedantic)

enable_testing()
add_test(NAME native_tests COMMAND native_tests)
