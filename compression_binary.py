import os
from time import perf_counter
from typing import Generator, Tuple


import numpy
from numpy.lib import recfunctions



# example line:
# [b'1539395563219', b'2018-10-13T01:52:43.219', b'unknown', b'0.01904296875', b'-0.00531005859375', b'-0.99017333984375']

def csv_to_list(file_contents: bytes) -> Tuple[bytes, Generator[bytes, None, None]]:
    """ Grab a list elements from of every line in the csv, strips off trailing whitespace. dumps
    them into a new list (of lists), and returns the header line along with the list of rows. """
    
    # This code is more memory efficient than fast by using a generator
    # Note that almost all of the time is spent in the per-row for-loop
    
    # case: the file coming in is just a single line, e.g. the header.
    # Need to provide the header and an empty iterator.
    if b"\n" not in file_contents:
        return file_contents, (_ for _ in ())
    
    line_iterator = isplit(file_contents)
    header = b",".join(next(line_iterator))
    header2 = file_contents[:file_contents.find(b"\n")]
    assert header2 == header, f"\n{header}\n{header2}"
    return header, line_iterator


def isplit(source: bytes) -> Generator[bytes, None, None]:
    """ Generator version of str.split()/bytes.split() """
    # version using str.find(), less overhead than re.finditer()
    start = 0
    while True:
        # find first split
        idx = source.find(b"\n", start)
        if idx == -1:
            yield source[start:].split(b",")
            return
        
        yield source[start:idx].split(b",")
        start = idx + 1


NaN = float("NaN")



def iterate_all_files():
    for user_path in os.listdir("./private/data"):
        for user_datastream in os.listdir(f"./private/data/{user_path}/"):
            if user_datastream != "accelerometer":
                continue
            user_datastream_path = f"./private/data/{user_path}/{user_datastream}/"
            for user_datastream_file in os.listdir(user_datastream_path):
                user_datastream_file_path = f"{user_datastream_path}/{user_datastream_file}"
                if not os.path.isdir(user_datastream_file_path):
                    with open(user_datastream_file_path, "rb") as f:
                        data: bytes = f.read()
                        if data:
                            yield user_datastream_file_path, data
                        # yield user_path, user_datastream, b"A" * 400000


class measurements:
    start_time = 0
    # total_time = 0
    total_compute_time = 0
    line_count = 0


def main():
    measurements.start_time = perf_counter()
    for path, data in iterate_all_files():
        # do_it_as_python(data, path)
        do_it_as_numpy(data, path)
        print(
            "total_compute_time:", f"{measurements.total_compute_time:.5f}", "time_per_row:",
            f"{measurements.total_compute_time/measurements.line_count:.10f}", "run time:",
            f"{perf_counter() - measurements.start_time :.5f}"
        )


def do_it_as_python(data: bytes, path: str):
    # total_compute_time: 7.72735 time_per_row: 0.0000006572 run time: 19.73537
    # pyston
    # total_compute_time: 3.98756 time_per_row: 0.0000003392 run time: 9.99690
    # python 3.11
    # total_compute_time: 5.47458 time_per_row: 0.0000004656 run time: 15.70931
    
    header, line_iterator = csv_to_list(data)
    output = []
    for timestamp, time_string, accuracy, x, y, z in line_iterator:
        measurements.line_count += 1
        # string_representation_1 = timestamp.decode().lower(), x.decode().lower(), y.decode().lower(), z.decode().lower(), accuracy.decode().lower() if accuracy == b"unknown" else accuracy.decode().lower()+".0"
        t1 = perf_counter()
        timestamp = int(timestamp)
        accuracy = NaN if accuracy == b"unknown" else float(accuracy)
        x = float(x)
        y = float(y)
        z = float(z)
        t2 = perf_counter()
        output.append((timestamp, accuracy, x, y, z, ))
        measurements.total_compute_time += (t2 - t1)
        # string_representation_2 = repr(timestamp), repr(x), repr(y), repr(z), "unknown" if accuracy is NaN else repr(accuracy)
        # print("accuracy.is_integer", accuracy.is_integer())
        # assert string_representation_1 == string_representation_2, print("", string_representation_1, "\n", string_representation_2)
        # print(" ".join(string_representation_2))


def do_it_as_numpy(data: bytes, path: str):
    # different measurements, longer one includes overhead of building lists:
    # total_compute_time: 6.05088 time_per_row: 0.0000005147 run time: 16.12444
    # total_compute_time: 15.36216 time_per_row: 0.0000013066 run time: 16.06826
    # pyston:
    # total_compute_time: 6.62630 time_per_row: 0.0000005636 run time: 12.26358
    # total_compute_time: 11.10675 time_per_row: 0.0000009447 run time: 11.73098
    # python 3.11
    # total_compute_time: 5.99982 time_per_row: 0.0000005103 run time: 14.65751
    # total_compute_time: 14.03839 time_per_row: 0.0000011940 run time: 14.70707
    
    header, line_iterator = csv_to_list(data)
    
    timestamps = []
    data = []
    t1 = perf_counter()
    for timestamp, time_string, accuracy, x, y, z in line_iterator:
        measurements.line_count += 1
        timestamps.append(timestamp)
        accuracy = NaN if accuracy == b"unknown" else accuracy
        data.append((accuracy, x, y, z, ))
    
    # t1 = perf_counter()
    ints = numpy.array(timestamps, dtype=numpy.uint64)
    # print(ints)
    floats = numpy.array(data, dtype=numpy.float64)
    # print("floats.nbytes:", floats.nbytes)
    # print("ints.nbytes:", ints.nbytes)
    # print(floats)
    t2 = perf_counter()
    measurements.total_compute_time += (t2 - t1)
    # ints = numpy.array(dtype=numpy.uint64, size=(1, csv_line_count_minus_1))
    # floats = numpy.array(dtype=numpy.float64, size=(4, csv_line_count_minus_1))


main()







# numpy stuff from someone who is not me

# # timestamp,UTC time,accuracy,x,y,z
# accel = "1524812805422,2018-04-27T07:06:45.422,unknown,-0.608657836914062,0.00982666015625,-0.816482543945312"

# NOT_A_NUMBER = float("NaN")
# # print("line:", accel)
# # print("base length:", len(accel))

# timestamp, _, accuracy, x, y, z = accel.split(",")

# timestamp_raw = int(timestamp)
# accuracy_raw = NOT_A_NUMBER if accuracy == "unknown" else float(accuracy)
# x_raw = float(x)
# y_raw = float(y)
# z_raw = float(z)

# # print("timestamp:", timestamp, timestamp_raw)
# # print("accuracy:", accuracy, accuracy_raw)
# # print("x:", x, x_raw)
# # print("y:", y, y_raw)
# # print("z:", z, z_raw)

# # print(numpy.array([timestamp_raw, accuracy_raw, x_raw, y_raw, z_raw], dtype=(numpy.uint, numpy.single)))

# ints = numpy.array((timestamp,))
# floats = numpy.array((accuracy_raw, x_raw, y_raw, z_raw))
# print("ints:", ints)
# print("floats:", floats)
# print(recfunctions.merge_arrays((ints, floats)))
# # dtypes = (numpy.uint, numpy.double, numpy.double, numpy.double, numpy.double)
# # print(numpy.array([timestamp_raw, accuracy_raw, x_raw, y_raw, z_raw], dtype=dtypes))