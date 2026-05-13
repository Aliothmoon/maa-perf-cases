add_executable(bench_matcher bench_matcher.cpp)

target_include_directories(bench_matcher PRIVATE
    ${PROJECT_SOURCE_DIR}/src/MaaCore
    ${PROJECT_SOURCE_DIR}/src/MaaUtils/include
)

target_link_libraries(bench_matcher PRIVATE MaaCore)
target_compile_features(bench_matcher PRIVATE cxx_std_20)

if(MSVC)
    target_compile_options(bench_matcher PRIVATE /WX-)
else()
    target_compile_options(bench_matcher PRIVATE -Wno-error)
endif()
