/** 浏览器有没有 IntersectionObserver（motion 的 whileInView 没有它会抛错；测试环境可能没有） */
export const canObserve = () => typeof IntersectionObserver !== 'undefined'
