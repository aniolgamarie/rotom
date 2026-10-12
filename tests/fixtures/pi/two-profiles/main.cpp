// 合成MVCC键值记录；没有外部数据库、业务数据或联网依赖。
#include <array>
#include <charconv>
#include <iostream>
#include <optional>
#include <string_view>
#include <system_error>

struct Version {
  int key;
  int commit;
  int value;
  bool deleted;
};

constexpr std::array<Version, 6> versions{{
  {7, 2, 11, false}, {7, 5, 22, false}, {7, 9, 0, true},
  {9, 3, 90, false}, {9, 7, 99, false}, {11, 5, 110, false}
}};

std::optional<int> lookup(int key, int snapshot) {
  const Version* visible = nullptr;
  for (const auto& version : versions) {
    // 待修复：snapshot应包含恰在该时刻提交的版本和删除记录。
    if (version.key == key && version.commit < snapshot &&
        (visible == nullptr || version.commit > visible->commit)) {
      visible = &version;
    }
  }
  if (visible == nullptr || visible->deleted) return std::nullopt;
  return visible->value;
}

bool number(std::string_view input, int& output) {
  const auto parsed = std::from_chars(input.data(), input.data() + input.size(), output);
  return parsed.ec == std::errc{} && parsed.ptr == input.data() + input.size();
}

int main(int argc, char** argv) {
  int key = 0, snapshot = 0;
  if (argc != 3 || !number(argv[1], key) || !number(argv[2], snapshot) || snapshot < 0) return 2;
  const auto value = lookup(key, snapshot);
  if (value) std::cout << "value=" << *value << '\n';
  else std::cout << "missing\n";
  return 0;
}
