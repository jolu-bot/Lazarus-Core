#pragma once
#include <vector>
#include <queue>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <future>
#include <atomic>
#include <stdexcept>

namespace lazarus {

class ThreadPool {
public:
    explicit ThreadPool(size_t num_threads = 0) {
        if (num_threads == 0)
            num_threads = std::max(1u, std::thread::hardware_concurrency());
        m_stop.store(false);
        m_workers.reserve(num_threads);
        for (size_t i = 0; i < num_threads; ++i) {
            m_workers.emplace_back([this] {
                while (true) {
                    std::function<void()> task;
                    {
                        std::unique_lock<std::mutex> lock(m_mutex);
                        m_cv.wait(lock, [this] {
                            return m_stop.load() || !m_queue.empty();
                        });
                        if (m_stop.load() && m_queue.empty()) return;
                        task = std::move(m_queue.front());
                        m_queue.pop();
                    }
                    task();
                    --m_active;
                    m_done_cv.notify_all();
                }
            });
        }
    }

    ~ThreadPool() { shutdown(); }

    template<typename F, typename... Args>
    auto enqueue(F&& f, Args&&... args)
        -> std::future<std::invoke_result_t<F, Args...>>
    {
        using R = std::invoke_result_t<F, Args...>;
        auto task = std::make_shared<std::packaged_task<R()>>(
            std::bind(std::forward<F>(f), std::forward<Args>(args)...)
        );
        std::future<R> fut = task->get_future();
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            if (m_stop.load()) throw std::runtime_error("ThreadPool stopped");
            m_queue.emplace([task]{ (*task)(); });
            ++m_active;
        }
        m_cv.notify_one();
        return fut;
    }

    void wait_all() {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_done_cv.wait(lock, [this] {
            return m_queue.empty() && m_active.load() == 0;
        });
    }

    void shutdown() {
        m_stop.store(true);
        m_cv.notify_all();
        for (auto& t : m_workers)
            if (t.joinable()) t.join();
        m_workers.clear();
    }

    size_t queue_size() const {
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_queue.size();
    }

    size_t thread_count() const { return m_workers.size(); }

private:
    std::vector<std::thread>          m_workers;
    std::queue<std::function<void()>> m_queue;
    mutable std::mutex                m_mutex;
    std::condition_variable           m_cv;
    std::condition_variable           m_done_cv;
    std::atomic<bool>                 m_stop{false};
    std::atomic<int>                  m_active{0};
};

} // namespace lazarus
